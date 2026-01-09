import socket
import threading
import json
import uuid
import time
import os
import netifaces
from crdt import RgaCrdt, HEAD
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QFontDialog,
    QApplication
)
from PyQt6.QtCore import Qt
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

        # Connect key events for CRDT
        self.text.keyPressEvent = self._on_key


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
                self.text.setPlainText(self.crdt.render())
            else:
                # Fallback for old-style snapshots (just text)
                text = msg.get("text", "")
                self.text.setPlainText(text)
                self.crdt = RgaCrdt()
            self.is_dirty = False
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
        
        cursor = self.text.textCursor()
        index = cursor.position()

        # Obsługa wklejania (Ctrl+V)
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_V:
            clipboard = QApplication.clipboard()
            text = clipboard.text()
            if text:
                self._broadcast_insert(index, text)
            # Pozwól domyślnej obsłudze wkleić tekst lokalnie
            QTextEdit.keyPressEvent(self.text, event)
            return

        if event.key() == Qt.Key.Key_Backspace:
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                self._broadcast_delete_range(start, end)
            else:
                # Brak zaznaczenia - Backspace usuwa znak na lewo od kursora
                self._broadcast_delete(index)

        elif event.key() == Qt.Key.Key_Delete:
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                self._broadcast_delete_range(start, end)
            else:
                # Delete usuwa znak po prawej stronie kursora (na pozycji 'index')
                # Żeby remote usunął znak 'index', musi ustawić kursor na 'index'.
                # _apply_remote_delete robi setPosition(msg["index"] - 1).
                # Więc msg["index"] musi wynosić index + 1.
                # Sprawdzamy też czy nie jesteśmy na końcu tekstu
                if index < len(self.text.toPlainText()):
                    self._broadcast_delete(index + 1)

        elif event.key() == Qt.Key.Key_Return:
            self._broadcast_insert(index, "\n")
        elif event.text() and (not event.modifiers() or event.modifiers() == Qt.KeyboardModifier.ShiftModifier):
            # Wysyłaj tylko drukowalne znaki, ignoruj skróty sterujące
            if event.text() >= ' ':
                self._broadcast_insert(index, event.text())
        
        QTextEdit.keyPressEvent(self.text, event)

    # --- CRDT broadcast helpers ---
    def next_op_id(self):
        """Generate a new CRDT operation ID as a tuple (counter, client_id)."""
        self.crdt_counter += 1
        return (self.client_id, self.crdt_counter)

    def _get_visible_id_map(self):
        """Get mapping of cursor positions to CRDT node IDs."""
        return self.crdt.visible_id_map()

    def _ensure_crdt_synced(self):
        """Ensure CRDT is synchronized with GUI text."""
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
            # If we have peers, send them the new state
            if self.peers:
                for peer_id in list(self.peers.keys()):
                    self._send_snapshot_to_peer(peer_id)

    def _broadcast_insert(self, index, text):
        """Broadcast CRDT insert operations for each character."""
        self._ensure_crdt_synced()
        id_map = self._get_visible_id_map()
        after_id = HEAD if index == 0 else id_map[index - 1]

        for ch in text:
            node_id = self.next_op_id()
            self.crdt.apply_insert(after_id, node_id, ch)
            op = {
                "type": "CRDT_INSERT",
                "after": list(after_id) if isinstance(after_id, tuple) else after_id,
                "node_id": list(node_id),
                "char": ch
            }
            self._send_to_peers(op)
            after_id = node_id

    def _broadcast_delete(self, index):
        """Broadcast a CRDT delete operation."""
        self._ensure_crdt_synced()
        id_map = self._get_visible_id_map()
        if index < 1 or index > len(id_map):
            return
        node_id = id_map[index - 1]
        self.crdt.apply_delete(node_id)
        op = {
            "type": "CRDT_DELETE",
            "node_id": list(node_id) if isinstance(node_id, tuple) else node_id
        }
        self._send_to_peers(op)

    def _broadcast_delete_range(self, start, end):
        """Broadcast CRDT delete operations for a range of characters."""
        self._ensure_crdt_synced()
        id_map = self._get_visible_id_map()
        if start < 0 or end > len(id_map):
            return
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

        if self.crdt.apply_insert(after, node_id, char):
            self._sync_text_from_crdt()

    def _apply_remote_delete(self, msg):
        """Apply a remote delete operation using CRDT."""
        node_id = tuple(msg["node_id"])

        if self.crdt.apply_delete(node_id):
            self._sync_text_from_crdt()

    def _sync_text_from_crdt(self):
        """Synchronize QTextEdit content with CRDT state."""
        self.applying_remote = True
        try:
            cursor = self.text.textCursor()
            old_pos = cursor.position()
            new_text = self.crdt.render()
            current_text = self.text.toPlainText()

            if new_text != current_text:
                self.text.setPlainText(new_text)
                cursor = self.text.textCursor()
                cursor.setPosition(min(old_pos, len(new_text)))
                self.text.setTextCursor(cursor)
        finally:
            self.applying_remote = False

    def _send_snapshot_to_peer(self, peer_id):
        peer = self.peers.get(peer_id)
        if not peer:
            return

        msg = {
            "type": "SNAPSHOT",
            "from_id": self.client_id,
            "from_name": self.user_name,
            "crdt_state": self.crdt.to_dict()
        }

        payload = json.dumps(msg).encode("utf-8")

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
