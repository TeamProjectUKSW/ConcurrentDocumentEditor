import socket
import threading
import json
import uuid
import time
import os
import netifaces
import gzip
from crdt import RgaCrdt, HEAD
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QFontDialog,
    QApplication
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtCore import pyqtSignal

def get_all_local_ips():
    """
    Retrieve all local IPv4 addresses and their broadcast addresses.

    Ignores loopback and link-local addresses.

    Returns:
        dict: Keys are local IP addresses, values are broadcast addresses.
    """
    ips = dict()
    try:
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
            for addr in addrs:
                ip = addr.get('addr')
                broadcast = addr.get('broadcast')
                if ip != "127.0.0.1" and not ip.startswith("169.254."):
                    ips[ip] = broadcast
        if not ips:
            raise Exception("No multiuser work enabled, check your internet connection")
    except Exception as e:
        print(e)
    return ips


class ConcurrentTextEditor(QWidget):
    """
    A PyQt6-based concurrent text editor with CRDT and UDP file sharing support.

    This editor allows multiple users to collaboratively edit a text file
    over a local network using UDP broadcasts and CRDT-based operational transforms.

    Attributes:
        user (User): Network configuration object for sending/listening UDP messages.
        client_id (str): Unique identifier of this client.
        user_name (str): Name of this user (defaults to client_id).
        peers (dict): Dictionary of connected peers.
        crdt_counter (int): Counter for CRDT operations.
        applying_remote (bool): Flag to avoid broadcasting remote changes.
        theme_state (int): Tracks current theme 0 = light, 1 = dark, 2 = cream 3 = mint.
        text (QTextEdit): Main text editing widget.
    """
    message_received = pyqtSignal(dict, tuple)
    def __init__(self):
        """Initialize the editor, GUI, network, and CRDT event handling."""
        super().__init__()
        self.message_received.connect(self._handle_message)
        self.seen_invites = set()

        self.setWindowTitle("Concurrent Text Editor")
        self.resize(800, 600)

        # Initialize network/user
        self.user = User(port_listen_=5005, port_send_=5010)
        self.client_id = str(uuid.uuid4())[:8]
        self.user_name = socket.gethostname()
        self.peers = {}
        self.crdt_counter = 0
        self.applying_remote = False
        self.crdt = RgaCrdt()  # Prawdziwy CRDT dla synchronizacji
        self.pending_ops = []  # Buffer for out-of-order operations
        self.cursor_node = HEAD  # Track cursor position as CRDT node ID

        #  GUI Setup
        self.is_dirty = False
        main_layout = QVBoxLayout()
        toolbar_layout = QHBoxLayout()
        main_layout.addLayout(toolbar_layout)
        self.setLayout(main_layout)

        # QTextEdit
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.textChanged.connect(self._on_modified)
        main_layout.addWidget(self.text)

        #  Toolbar buttons
        self._add_toolbar_button(toolbar_layout, "Open", self.open_file)
        self._add_toolbar_button(toolbar_layout, "Save", self.save_file)
        self._add_toolbar_button(toolbar_layout, "Save as", self.saveas_file)
        self._add_toolbar_button(toolbar_layout, "Share", self.share_file)
        self._add_toolbar_button(toolbar_layout, "Disconnect", self.leave_session)
        self._add_toolbar_button(toolbar_layout, "Add test", self.insert_test_text)
        self._add_toolbar_button(toolbar_layout, "Change font", self.change_font)
        self._add_toolbar_button(toolbar_layout, "Toggle theme", self.toggle_theme)

        # -Default theme
        self.theme_state = 0  # 0=light, 1=dark, 2=navy
        self.set_light_theme()

        # Start listening thread
        self.get_shared_file()

        # Anti-Entropy / Consistency Check Timer
        self.consistency_timer = QTimer(self)
        self.consistency_timer.timeout.connect(self._broadcast_state_check)
        self.consistency_timer.start(3000)  # Check every 3 seconds

        # Connect key events for CRDT
        self.text.keyPressEvent = self._on_key
        # Update cursor_node when user clicks or navigates
        self.text.cursorPositionChanged.connect(self._on_cursor_changed)

    def _on_cursor_changed(self):
        """Update cursor_node when cursor position changes (click, navigation)."""
        if not self.applying_remote:
            self._update_cursor_node_from_position()


    #  GUI helper
    def _add_toolbar_button(self, layout, text, callback):
        """
        Add a QPushButton to the toolbar with a given label and callback.

        Args:
            layout (QLayout): The toolbar layout to add the button to.
            text (str): Button label.
            callback (function): Function to call when button is clicked.
        """
        btn = QPushButton(text)
        btn.clicked.connect(callback)
        layout.addWidget(btn)

    #  Theme methods
    def set_light_theme(self):
        """Set a light theme for the editor."""
        self.setStyleSheet("""
            QWidget { background-color: #f9f9f9; color: #1e1e1e; }
            QTextEdit { background-color: #ffffff; color: #000000; }
            QPushButton { background-color: #e0e0e0; color: #1e1e1e; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #d0d0d0; }
        """)
        self.theme_state = 0

    def set_dark_theme(self):
        """Set a dark theme for the editor."""
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #f0f0f0; }
            QTextEdit { background-color: #3c3f41; color: #f0f0f0; }
            QPushButton { background-color: #505357; color: #f0f0f0; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #606367; }
        """)
        self.theme_state = 1

    def set_cream_theme(self):
        """Set a warm cream theme, easy on the eyes for text editing."""
        self.setStyleSheet("""
            QWidget { background-color: #fff8e7; color: #2e2e2e; }
            QTextEdit { background-color: #fffdf4; color: #1e1e1e; }
            QPushButton { background-color: #f0e6d2; color: #2e2e2e; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #e6dabe; }
        """)
        self.theme_state = 2  # przypisujemy nowy stan

    def set_mint_theme(self):
        """Set a soft mint theme for a fresh look."""
        self.setStyleSheet("""
            QWidget { background-color: #e6f7f1; color: #1e1e1e; }
            QTextEdit { background-color: #f0fcf9; color: #1e1e1e; }
            QPushButton { background-color: #ccebe1; color: #1e1e1e; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #b3ded2; }
        """)
        self.theme_state = 3

    def toggle_theme(self):
        """Cycle through available themes"""
        if self.theme_state == 0:
            self.set_dark_theme()
        elif self.theme_state == 1:
            self.set_cream_theme()
        elif self.theme_state == 2:
            self.set_mint_theme()
        else:
            self.set_light_theme()

    # - Font selection
    def change_font(self):
        """Open a font selection dialog and apply the chosen font to the editor."""
        font, ok = QFontDialog.getFont()
        if ok:
            self.text.setFont(font)

    # --- File/Editor logic ---
    def _on_modified(self):
        """Mark document as modified when text changes."""
        self.is_dirty = True

    def open_file(self):
        """Open a text file and load its contents into the editor."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Open file", "", "Text files (*.txt);;All files (*)")
        if not file_path:
            return
        with open(file_path, "r", encoding="utf-8") as f:
            self.text.setPlainText(f.read())
        self.current_file_path = file_path
        self.setWindowTitle(f"Text editor - {file_path}")
        self.is_dirty = False

    def save_file(self):
        """Save current file, or prompt Save As if no file exists."""
        if not getattr(self, "current_file_path", None):
            return self.saveas_file()
        content = self.text.toPlainText()
        with open(self.current_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        QMessageBox.information(self, "Saved", f"File saved:\n{self.current_file_path}")
        self.is_dirty = False

    def saveas_file(self):
        """Open Save As dialog and save editor content to a chosen path."""
        file_path, _ = QFileDialog.getSaveFileName(self, "Save file", "", "Text files (*.txt);;All files (*)")
        if not file_path:
            return
        dir_name = os.path.dirname(file_path)
        if dir_name and not os.path.exists(dir_name):
            QMessageBox.critical(self, "Error", "Path does not exist!")
            return
        self.current_file_path = file_path
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.text.toPlainText())
        QMessageBox.information(self, "Saved", f"File saved as:\n{file_path}")
        self.is_dirty = False

    def insert_test_text(self):
        """Append sample text to the editor for testing purposes."""
        self.text.append("Hello world!")

    def _apply_snapshot(self, msg):
        self.applying_remote = True
        try:
            crdt_state = msg.get("crdt_state")
            if crdt_state:
                self.crdt = RgaCrdt.from_dict(crdt_state)
                rendered = self.crdt.render()
                print(f"[CRDT] SNAPSHOT RECEIVED: {len(crdt_state.get('nodes', []))} nodes")
                
                # Update Lamport Clock based on snapshot data
                max_counter = self.crdt_counter
                for node in self.crdt.nodes.keys():
                    if isinstance(node, tuple) and len(node) == 2 and isinstance(node[0], int):
                        if node[0] > max_counter:
                            max_counter = node[0]
                self._update_lamport_clock(max_counter)
                
                self.text.setPlainText(rendered)
            else:
                # Fallback for old-style snapshots (just text)
                text = msg.get("text", "")
                print(f"[CRDT] SNAPSHOT RECEIVED (old style): text='{text[:50]}...'")
                self.text.setPlainText(text)
                self.crdt = RgaCrdt()
            
            # Clear pending ops - snapshot replaces everything
            self.pending_ops.clear()
            self.is_dirty = False

            # Validate cursor_node against new CRDT state
            if self.cursor_node != HEAD and self.cursor_node not in self.crdt.nodes:
                print(f"[SYNC] Cursor node {self.cursor_node} missing in snapshot, falling back.")
                # Walk up ancestors if possible, or just reset to HEAD
                # For simplicity and safety after snapshot, reset to HEAD if missing
                self.cursor_node = HEAD

            # Restore cursor based on node ID (sticky)
            new_pos = self._get_cursor_position_from_node()
            cursor = self.text.textCursor()
            cursor.setPosition(min(new_pos, len(self.text.toPlainText())))
            self.text.setTextCursor(cursor)

        finally:
            self.applying_remote = False

    def _handle_invite(self, msg, addr):
        if msg.get("from_id") == self.client_id:
            return

        # Jeśli już jesteśmy połączeni z tym nadawcą, ignorujemy zaproszenie
        if msg.get("from_id") in self.peers:
            return

        invite_id = msg.get("invite_id")

        if invite_id in self.seen_invites:
            return

        # ✅ zapamiętaj że już obsłużone
        self.seen_invites.add(invite_id)

        def ask():
            reply = QMessageBox.question(
                self,
                "Share request",
                f"{msg.get('from_name', 'Inny użytkownik')} chce współdzielić dokument.\nAkceptujesz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

            if getattr(self, "is_dirty", False):
                decision = self._prompt_unsaved_before_join()

                if decision == "cancel":
                    return
                if decision == "save":
                    self.save_file()
                    if getattr(self, "is_dirty", False):
                        return

            peer_ip = addr[0]
            peer_port = msg["listen_port"]

            self._add_peer(
                msg["from_id"],
                peer_ip,
                peer_port,
                msg.get("from_name", peer_ip)
            )

            response = {
                "type": "INVITE_ACCEPT",
                "from_id": self.client_id,
                "from_name": self.user_name,
                "listen_port": self.user.port_listen
            }

            payload = json.dumps(response).encode("utf-8")
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload, (peer_ip, peer_port))

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, ask)

    def _handle_invite_accept(self, msg, addr):
        peer_ip = addr[0]
        peer_port = msg["listen_port"]
        new_peer_id = msg["from_id"]
        new_peer_name = msg["from_name"]

        # Notify existing peers about the new peer AND notify the new peer about existing peers
        for existing_id, existing_peer in self.peers.items():
            # Tell existing peer about the new guy
            self._send_peer_announce(
                target_ip=existing_peer["ip"],
                target_port=existing_peer["port"],
                peer_id=new_peer_id,
                peer_name=new_peer_name,
                peer_ip=peer_ip,
                peer_port=peer_port
            )
            # Tell the new guy about the existing peer
            self._send_peer_announce(
                target_ip=peer_ip,
                target_port=peer_port,
                peer_id=existing_id,
                peer_name=existing_peer["name"],
                peer_ip=existing_peer["ip"],
                peer_port=existing_peer["port"]
            )

        self._add_peer(new_peer_id, peer_ip, peer_port, new_peer_name)

        QMessageBox.information(
            self,
            "Share",
            f"{new_peer_name} dołączył do sesji."
        )

        self._send_snapshot_to_peer(new_peer_id)

    def _handle_message(self, msg, addr):

        if msg.get("from_id") == self.client_id:
            return

        print(
            f"[RECV] from={addr} type={msg.get('type')} from_id={msg.get('from_id')} from_name={msg.get('from_name')}")
        print(f"[ME]   my_id={self.client_id} my_name={self.user_name}")

        msg_type = msg.get("type")

        if msg_type == "INVITE":
            self._handle_invite(msg, addr)

        elif msg_type == "INVITE_ACCEPT":
            self._handle_invite_accept(msg, addr)

        elif msg_type == "PEER_ANNOUNCE":
            self._handle_peer_announce(msg)

        elif msg_type == "PEER_LEAVE":
            self._handle_peer_leave(msg)

        elif msg_type == "CRDT_INSERT":
            self._apply_remote_insert(msg)

        elif msg_type == "CRDT_DELETE":
            self._apply_remote_delete(msg)
        elif msg_type == "SNAPSHOT":
            self._apply_snapshot(msg)

        elif msg_type == "STATE_CHECK":
            self._handle_state_check(msg, addr)

        elif msg_type == "REQUEST_SNAPSHOT":
            self._send_snapshot_to_peer(msg.get("from_id"))

    def leave_session(self):
        """Leave the current session, disconnect from peers, and continue offline."""
        if not self.peers:
            QMessageBox.information(self, "Disconnect", "Nie jesteś połączony z żadną sesją.")
            return

        # Notify peers that I'm leaving
        msg = {
            "type": "PEER_LEAVE",
            "from_id": self.client_id
        }
        self._send_to_peers(msg)
        
        # Clear local peers list
        self.peers.clear()
        # Reset seen invites so we can rejoin later if needed
        self.seen_invites.clear()
        
        QMessageBox.information(self, "Disconnect", "Rozłączono z sesji. Możesz kontynuować pracę lokalnie.")

    def _handle_peer_leave(self, msg):
        """Handle a peer leaving the session."""
        peer_id = msg.get("from_id")
        if peer_id in self.peers:
            peer_name = self.peers[peer_id]["name"]
            del self.peers[peer_id]
            # Opcjonalnie: można to zrobić jako dyskretny status bar message zamiast popupu, 
            # ale trzymajmy się konwencji QMessageBox na razie.
            QMessageBox.information(self, "Info", f"{peer_name} opuścił sesję.")

    def _handle_peer_announce(self, msg):
        """Handle incoming peer announcement and connect to the new peer."""
        p_id = msg["peer_id"]
        if p_id == self.client_id:
            return
        if p_id in self.peers:
            return  # Already known

        self._add_peer(p_id, msg["peer_ip"], msg["peer_port"], msg["peer_name"])

    def _send_peer_announce(self, target_ip, target_port, peer_id, peer_name, peer_ip, peer_port):
        """Send a PEER_ANNOUNCE message to a specific target."""
        msg = {
            "type": "PEER_ANNOUNCE",
            "peer_id": peer_id,
            "peer_name": peer_name,
            "peer_ip": peer_ip,
            "peer_port": peer_port
        }
        payload = json.dumps(msg).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (target_ip, target_port))

    def _add_peer(self, peer_id, ip, port, name):
        self.peers[peer_id] = {
            "ip": ip,
            "port": port,
            "name": name,
            "last_seen": time.time()
        }
        print(f"[PEER] Dodano {name} ({ip}:{port})")

    # --- Anti-Entropy Logic ---
    def _broadcast_state_check(self):
        """Periodically broadcast current state hash to detect desynchronization."""
        if not self.peers:
            return

        current_hash = self.crdt.state_hash()
        node_count = len(self.crdt.nodes)

        msg = {
            "type": "STATE_CHECK",
            "from_id": self.client_id,
            "state_hash": current_hash,
            "node_count": node_count
        }
        self._send_to_peers(msg)

    def _handle_state_check(self, msg, addr):
        """Handle incoming state check. If divergent, request or send snapshot."""
        remote_hash = msg.get("state_hash")
        remote_count = msg.get("node_count", 0)
        sender_id = msg.get("from_id")

        if sender_id not in self.peers:
            return

        my_hash = self.crdt.state_hash()
        my_count = len(self.crdt.nodes)

        if remote_hash == my_hash:
            return  # States are consistent

        print(f"[SYNC] Inconsistency detected with {sender_id}. Me: {my_count} nodes, Them: {remote_count} nodes.")

        # Simple resolution strategy:
        # If I have more data (nodes), I assume I am 'ahead' and send a snapshot.
        # If they have more data, I ask for a snapshot.
        # If equal nodes but different hash (rare collision/divergence), tie-break by client_id.

        if my_count > remote_count:
            print(f"[SYNC] Sending snapshot to {sender_id} (I have more data).")
            self._send_snapshot_to_peer(sender_id)
        elif my_count < remote_count:
            print(f"[SYNC] Requesting snapshot from {sender_id} (They have more data).")
            self._request_snapshot(sender_id)
        else:
            # Equal node count but different content. Tie-breaker.
            if self.client_id > sender_id:
                print(f"[SYNC] Tie-break: Sending snapshot to {sender_id}.")
                self._send_snapshot_to_peer(sender_id)
            else:
                # I'll wait for them to send (or request explicitly if impatient)
                pass

    def _request_snapshot(self, peer_id):
        """Send a request for a snapshot to a specific peer."""
        peer = self.peers.get(peer_id)
        if not peer:
            return
        
        msg = {
            "type": "REQUEST_SNAPSHOT",
            "from_id": self.client_id
        }
        payload = json.dumps(msg).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (peer["ip"], peer["port"]))

    # --- CRDT/Networking logic ---
    def get_shared_file(self):
        def listen():
            self.auto_select_ip()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', self.user.port_listen))
            print(f"[UDP] Listening on {self.user.port_listen} ...")
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                    
                    # Try to decompress, assuming it might be gzipped
                    try:
                        decompressed = gzip.decompress(data)
                        data = decompressed
                    except (gzip.BadGzipFile, OSError):
                        # Not gzipped, treat as raw bytes
                        pass

                    msg = json.loads(data.decode("utf-8"))

                    # 🔥 PRZEJŚCIE DO WĄTKU GUI
                    self.message_received.emit(msg, addr)

                except Exception as e:
                    print("[UDP ERROR]", e)

        threading.Thread(target=listen, daemon=True).start()

    def auto_select_ip(self):
        """Automatically select a local IP and broadcast address for networking."""
        ips = get_all_local_ips()
        ip, bcast = next(iter(ips.items()))
        self.user.host = ip
        self.user.bcast = bcast
        print(f"[NET] Using {ip} / {bcast}")

    def share_file(self):
        """Broadcast an INVITE message to peers on the local network."""
        # Sync CRDT with GUI before sharing so peers get correct state
        self._ensure_crdt_synced()
        self.invite_id = str(uuid.uuid4())
        msg = {
            "type": "INVITE",
            "invite_id": self.invite_id,
            "from_id": self.client_id,
            "from_name": self.user_name,
            "listen_port": self.user.port_listen
        }
        payload = json.dumps(msg).encode("utf-8")
        ips = get_all_local_ips()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for ip, bcast in ips.items():
                try:
                    sock.sendto(payload, (bcast, self.user.port_listen))
                except Exception:
                    pass
        QMessageBox.information(self, "Share", "Zaproszenie wysłane. Czekam na odpowiedzi.")

    def _on_key(self, event):
        """Handle key events for broadcasting CRDT inserts/deletes (Qt version)."""
        if self.applying_remote:
            return

        # Update cursor_node from current GUI position before any operation
        self._update_cursor_node_from_position()

        cursor = self.text.textCursor()
        index = cursor.position()

        # Obsługa wklejania (Ctrl+V)
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_V:
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            if text:
                self._broadcast_insert(index, text)
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
            return

        if event.key() == Qt.Key.Key_Backspace:
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                self._broadcast_delete_range(start, end)
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
                return
            else:
                # Brak zaznaczenia - Backspace usuwa znak na lewo od kursora
                if index > 0:
                    self._broadcast_delete(index)
                    self._sync_text_from_crdt()
                    self._move_cursor(self._get_cursor_position_from_node())
                return

        elif event.key() == Qt.Key.Key_Delete:
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                self._broadcast_delete_range(start, end)
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
                return
            else:
                # Delete usuwa znak po prawej stronie kursora (na pozycji 'index')
                if index < len(self.text.toPlainText()):
                    self._broadcast_delete(index + 1)
                    self._sync_text_from_crdt()
                    self._move_cursor(self._get_cursor_position_from_node())
                return

        elif event.key() == Qt.Key.Key_Return:
            self._broadcast_insert(index, "\n")
            self._sync_text_from_crdt()
            self._move_cursor(self._get_cursor_position_from_node())
            return  # Don't let Qt handle it
        
        elif event.text():
            # Simply check if it's a printable character (>= space).
            # We trust Qt: if it produced text, it's text.
            # This fixes Windows AltGr (Ctrl+Alt) being blocked.
            if event.text() >= ' ':
                self._broadcast_insert(index, event.text())
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
                return  # Don't let Qt handle it - CRDT is source of truth

        # For navigation keys (arrows, etc.), let Qt handle and then update cursor_node
        QTextEdit.keyPressEvent(self.text, event)
        self._update_cursor_node_from_position()

    # --- CRDT broadcast helpers ---
    def next_op_id(self):
        """Generate a new CRDT operation ID as a tuple (counter, client_id)."""
        self.crdt_counter += 1
        return (self.crdt_counter, self.client_id)

    def _update_lamport_clock(self, remote_counter):
        """Update local counter to be at least remote_counter."""
        if remote_counter > self.crdt_counter:
            self.crdt_counter = remote_counter

    def _get_visible_id_map(self):
        """Get mapping of cursor positions to CRDT node IDs."""
        return self.crdt.visible_id_map()

    def _ensure_crdt_synced(self):
        """Ensure CRDT is synchronized with GUI text. Only call before starting a session."""
        gui_text = self.text.toPlainText()
        crdt_text = self.crdt.render()
        if gui_text != crdt_text:
            # Rebuild CRDT from GUI text
            self.crdt = RgaCrdt()
            after_id = HEAD
            for ch in gui_text:
                node_id = self.next_op_id()
                self.crdt.apply_insert(after_id, node_id, ch)
                after_id = node_id

    def _update_cursor_node_from_position(self):
        """Update cursor_node based on current GUI cursor position."""
        cursor = self.text.textCursor()
        pos = cursor.position()
        id_map = self._get_visible_id_map()
        if pos == 0:
            self.cursor_node = HEAD
        elif pos <= len(id_map):
            self.cursor_node = id_map[pos - 1]
        elif id_map:
            self.cursor_node = id_map[-1]
        else:
            self.cursor_node = HEAD

    def _get_cursor_position_from_node(self):
        """Get GUI position from cursor_node."""
        if self.cursor_node == HEAD:
            return 0
        id_map = self._get_visible_id_map()
        
        # Try to find the exact node
        for i, node_id in enumerate(id_map):
            if node_id == self.cursor_node:
                return i + 1
        
        # Node not found (deleted). Fallback to nearest visible ancestor.
        # Walk up the 'after' chain until we find a visible node or HEAD.
        current_id = self.cursor_node
        while current_id != HEAD:
            if current_id not in self.crdt.nodes:
                # Should not happen if data is consistent, but safety first
                current_id = HEAD
                break
            
            node = self.crdt.nodes[current_id]
            if not node.deleted:
                # Found a visible ancestor. Find its position in the map.
                for i, visible_id in enumerate(id_map):
                    if visible_id == current_id:
                        return i + 1
                # If marked not deleted but not in id_map? Odd, keep searching.
            
            current_id = node.after

        # If we reached HEAD (or fell through), cursor goes to start
        return 0

    def _broadcast_insert(self, index, text):
        """Broadcast CRDT insert operations for each character."""
        # Use cursor_node instead of GUI position
        after_id = self.cursor_node

        for ch in text:
            node_id = self.next_op_id()
            self.crdt.apply_insert(after_id, node_id, ch)
            print(f"[CRDT] LOCAL INSERT: '{ch}' node={node_id} after={after_id}")
            op = {
                "type": "CRDT_INSERT",
                "after": list(after_id) if isinstance(after_id, tuple) else after_id,
                "node_id": list(node_id),
                "char": ch
            }
            self._send_to_peers(op)
            after_id = node_id

        # Update cursor to last inserted node
        self.cursor_node = after_id

    def _broadcast_delete(self, index):
        """Broadcast a CRDT delete operation."""
        id_map = self._get_visible_id_map()
        if index < 1 or index > len(id_map):
            return
        node_id = id_map[index - 1]
        # Update cursor to node before the deleted one
        self.cursor_node = id_map[index - 2] if index >= 2 else HEAD
        self.crdt.apply_delete(node_id)
        op = {
            "type": "CRDT_DELETE",
            "node_id": list(node_id) if isinstance(node_id, tuple) else node_id
        }
        self._send_to_peers(op)

    def _broadcast_delete_range(self, start, end):
        """Broadcast CRDT delete operations for a range of characters."""
        id_map = self._get_visible_id_map()
        if start < 0 or end > len(id_map):
            return
        # Update cursor to node before the deleted range
        self.cursor_node = id_map[start - 1] if start >= 1 else HEAD
        # Collect all node IDs first (before any deletions)
        node_ids = [id_map[i] for i in range(start, end)]
        for node_id in node_ids:
            self.crdt.apply_delete(node_id)
            op = {
                "type": "CRDT_DELETE",
                "node_id": list(node_id) if isinstance(node_id, tuple) else node_id
            }
            self._send_to_peers(op)

    def _send_to_peers(self, msg):
        """Send a JSON message via UDP to all connected peers."""
        payload = json.dumps(msg).encode("utf-8")
        for peer in self.peers.values():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload, (peer["ip"], peer["port"]))

    def _apply_remote_insert(self, msg):
        """Apply a remote insert operation using CRDT."""
        after = tuple(msg["after"]) if isinstance(msg["after"], list) else msg["after"]
        node_id = tuple(msg["node_id"])
        char = msg["char"]

        # Update Lamport Clock
        self._update_lamport_clock(node_id[0])

        if self.crdt.apply_insert(after, node_id, char):
            print(f"[CRDT] INSERT OK: '{char}' node={node_id} after={after}")
            self._flush_pending_ops()
            self._sync_text_from_crdt()
        else:
            # Buffer operation if 'after' node doesn't exist yet
            print(f"[CRDT] INSERT PENDING: '{char}' node={node_id} after={after} (after not found)")
            self.pending_ops.append(("insert", after, node_id, char))

    def _apply_remote_delete(self, msg):
        """Apply a remote delete operation using CRDT."""
        node_id = tuple(msg["node_id"])

        if self.crdt.apply_delete(node_id):
            print(f"[CRDT] DELETE OK: node={node_id}")
            self._sync_text_from_crdt()
        else:
            # Buffer operation if node doesn't exist yet
            print(f"[CRDT] DELETE PENDING: node={node_id} (not found)")
            self.pending_ops.append(("delete", node_id))

    def _flush_pending_ops(self):
        """Try to apply buffered operations that were waiting for dependencies."""
        if not self.pending_ops:
            return

        print(f"[CRDT] Flushing {len(self.pending_ops)} pending ops...")
        made_progress = True
        while made_progress:
            made_progress = False
            remaining = []
            for op in self.pending_ops:
                if op[0] == "insert":
                    _, after, node_id, char = op
                    if self.crdt.apply_insert(after, node_id, char):
                        print(f"[CRDT] FLUSH INSERT OK: '{char}' node={node_id}")
                        made_progress = True
                    else:
                        remaining.append(op)
                elif op[0] == "delete":
                    _, node_id = op
                    if self.crdt.apply_delete(node_id):
                        print(f"[CRDT] FLUSH DELETE OK: node={node_id}")
                        made_progress = True
                    else:
                        remaining.append(op)
            self.pending_ops = remaining
        if self.pending_ops:
            print(f"[CRDT] Still {len(self.pending_ops)} pending ops remaining")

    def _sync_text_from_crdt(self):
        """Synchronize QTextEdit content with CRDT state."""
        self.applying_remote = True
        try:
            # We don't rely on integer position anymore, but on self.cursor_node
            new_text = self.crdt.render()
            current_text = self.text.toPlainText()

            if new_text != current_text:
                # print(f"[CRDT] SYNC: '{current_text}' -> '{new_text}'")
                self.text.setPlainText(new_text)
                
                # Restore cursor based on cursor_node (sticky cursor)
                new_pos = self._get_cursor_position_from_node()
                cursor = self.text.textCursor()
                cursor.setPosition(min(new_pos, len(new_text)))
                self.text.setTextCursor(cursor)
        finally:
            self.applying_remote = False

    def _move_cursor(self, position):
        """Move cursor to specified position."""
        cursor = self.text.textCursor()
        cursor.setPosition(min(position, len(self.text.toPlainText())))
        self.text.setTextCursor(cursor)

    def _send_snapshot_to_peer(self, peer_id):
        peer = self.peers.get(peer_id)
        if not peer:
            return

        crdt_dict = self.crdt.to_dict()
        print(f"[CRDT] SNAPSHOT SEND to {peer['name']}: {len(crdt_dict.get('nodes', []))} nodes")

        msg = {
            "type": "SNAPSHOT",
            "from_id": self.client_id,
            "from_name": self.user_name,
            "crdt_state": crdt_dict
        }

        payload = json.dumps(msg).encode("utf-8")
        # Compress payload to avoid Message too long error
        payload = gzip.compress(payload)

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (peer["ip"], peer["port"]))

    def _prompt_unsaved_before_join(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Niezapisane zmiany")
        msg.setText(
            "Masz niezapisane zmiany.\n"
            "Dołączenie do sesji nadpisze bieżącą zawartość.\n"
            "Co robimy?"
        )

        save_btn = msg.addButton("Zapisz zmiany", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("Odrzuć zmiany", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        clicked = msg.clickedButton()
        if clicked == save_btn:
            return "save"
        elif clicked == discard_btn:
            return "discard"
        return "cancel"


class User:
    """Network configuration for sending and receiving UDP messages."""

    def __init__(self, port_listen_=5005, port_send_=5010):
        """
        Initialize a User network object.

        Args:
            port_listen_ (int): UDP port to listen for incoming messages.
            port_send_ (int): UDP port to send outgoing messages.
        """
        self.host = ''
        self.port_listen = port_listen_
        self.port_send = port_send_
        self.bcast = '255.255.255.255'
