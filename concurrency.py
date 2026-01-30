import socket
import threading
import json
import uuid
import time
import netifaces
import gzip
import base64
from crdt import RgaCrdt, HEAD
from PyQt6.QtWidgets import (
    QTextEdit,
    QMessageBox,
    QApplication,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtCore import pyqtSignal
from editor import BaseTextEditor


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
                ip = addr.get("addr")
                broadcast = addr.get("broadcast")
                if ip and ip != "127.0.0.1" and not ip.startswith("169.254."):
                    ips[ip] = broadcast
        if not ips:
            raise Exception("No multiuser work enabled, check your internet connection")
    except Exception as e:
        print(e)
    return ips


class ConcurrentTextEditor(BaseTextEditor):
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

        self.user = User(port_listen_=5005, port_send_=5010)
        self.client_id = str(uuid.uuid4())[:8]
        self.user_name = socket.gethostname()
        self.peers = {}
        self.crdt_counter = 0
        self.applying_remote = False
        self.crdt = RgaCrdt()
        self.pending_ops = []
        self.cursor_node = HEAD
        self.chunk_buffer = {}

        self.is_dirty = False

        self.get_shared_file()

        self.consistency_timer = QTimer(self)
        self.consistency_timer.timeout.connect(self._broadcast_state_check)
        self.consistency_timer.start(3000)

        self.text.keyPressEvent = self._on_key

        self.text.cursorPositionChanged.connect(self._on_cursor_changed)
        self.text.installEventFilter(self)

    def _on_cursor_changed(self):
        """Update cursor_node when cursor position changes (click, navigation)."""
        if not self.applying_remote:
            self._update_cursor_node_from_position()

    def _apply_snapshot(self, msg):
        self.applying_remote = True
        try:
            crdt_state = msg.get("crdt_state")
            if crdt_state:
                old_crdt = self.crdt
                new_crdt = RgaCrdt.from_dict(crdt_state)

                self.crdt = new_crdt
                rendered = self.crdt.render()
                print(
                    f"[CRDT] SNAPSHOT RECEIVED: {len(crdt_state.get('nodes', []))} nodes"
                )

                max_counter = self.crdt_counter
                for node in self.crdt.nodes.keys():
                    if (
                        isinstance(node, tuple)
                        and len(node) == 2
                        and isinstance(node[0], int)
                    ):
                        if node[0] > max_counter:
                            max_counter = node[0]
                self._update_lamport_clock(max_counter)

                self.text.setPlainText(rendered)

                self.pending_ops.clear()
                self.is_dirty = False

                if self.cursor_node != HEAD and self.cursor_node not in self.crdt.nodes:
                    print(
                        f"[SYNC] Cursor node {self.cursor_node} missing in snapshot, searching for ancestor in old graph."
                    )

                    current_id = self.cursor_node
                    found_ancestor = HEAD

                    for _ in range(1000):
                        if current_id == HEAD:
                            break

                        if current_id not in old_crdt.nodes:
                            break

                        node = old_crdt.nodes[current_id]
                        parent_id = node.after

                        if parent_id in self.crdt.nodes:
                            found_ancestor = parent_id
                            break

                        current_id = parent_id

                    self.cursor_node = found_ancestor

                new_pos = self._get_cursor_position_from_node()
                cursor = self.text.textCursor()
                cursor.setPosition(min(new_pos, len(self.text.toPlainText())))
                self.text.setTextCursor(cursor)

            else:
                text = msg.get("text", "")
                print(f"[CRDT] SNAPSHOT RECEIVED (old style): text='{text[:50]}...'")
                self.text.setPlainText(text)
                self.crdt = RgaCrdt()
                self.pending_ops.clear()
                self.is_dirty = False

                self.cursor_node = HEAD

        finally:
            self.applying_remote = False

    def _handle_invite(self, msg, addr):
        if msg.get("from_id") == self.client_id:
            return

        if msg.get("from_id") in self.peers:
            return

        invite_id = msg.get("invite_id")

        if invite_id in self.seen_invites:
            return

        self.seen_invites.add(invite_id)

        def ask():
            reply = QMessageBox.question(
                self,
                "Share request",
                f"{msg.get('from_name', 'Inny użytkownik')} wants to collaborate with the document.\nAccept?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
                msg["from_id"], peer_ip, peer_port, msg.get("from_name", peer_ip)
            )

            response = {
                "type": "INVITE_ACCEPT",
                "from_id": self.client_id,
                "from_name": self.user_name,
                "listen_port": self.user.port_listen,
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

        for existing_id, existing_peer in self.peers.items():
            self._send_peer_announce(
                target_ip=existing_peer["ip"],
                target_port=existing_peer["port"],
                peer_id=new_peer_id,
                peer_name=new_peer_name,
                peer_ip=peer_ip,
                peer_port=peer_port,
            )

            self._send_peer_announce(
                target_ip=peer_ip,
                target_port=peer_port,
                peer_id=existing_id,
                peer_name=existing_peer["name"],
                peer_ip=existing_peer["ip"],
                peer_port=existing_peer["port"],
            )

        self._add_peer(new_peer_id, peer_ip, peer_port, new_peer_name)

        QMessageBox.information(self, "Share", f"{new_peer_name} joined the session.")

        self._send_snapshot_to_peer(new_peer_id)

    def _handle_message(self, msg, addr):
        if msg.get("from_id") == self.client_id:
            return

        msg_type = msg.get("type")

        if msg_type == "CHUNK":
            self._handle_chunk(msg, addr)
            return

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

    def _handle_chunk(self, msg, addr):
        """Reassemble chunked messages."""
        msg_id = msg.get("id")
        chunk_idx = msg.get("i")
        total_chunks = msg.get("n")
        data_b64 = msg.get("data")

        if not (msg_id and total_chunks and data_b64 is not None):
            return

        if msg_id not in self.chunk_buffer:
            self.chunk_buffer[msg_id] = [None] * total_chunks

        try:
            chunk_data = base64.b64decode(data_b64)
            self.chunk_buffer[msg_id][chunk_idx] = chunk_data
        except Exception as e:
            print(f"[CHUNK] Error decoding chunk: {e}")
            return

        if all(c is not None for c in self.chunk_buffer[msg_id]):
            full_data = b"".join(self.chunk_buffer[msg_id])
            del self.chunk_buffer[msg_id]

            try:
                try:
                    decompressed = gzip.decompress(full_data)
                    full_data = decompressed
                except (gzip.BadGzipFile, OSError):
                    pass

                full_msg = json.loads(full_data.decode("utf-8"))
                print(f"[CHUNK] Reassembled message {msg_id} ({len(full_data)} bytes)")

                self._handle_message(full_msg, addr)
            except Exception as e:
                print(f"[CHUNK] Error processing reassembled message: {e}")

    def leave_session(self):
        """Leave the current session, disconnect from peers, and continue offline."""
        if not self.peers:
            QMessageBox.information(
                self, "Disconnect", "You are not connected with any session."
            )
            return

        msg = {"type": "PEER_LEAVE", "from_id": self.client_id}
        self._send_to_peers(msg)

        self.peers.clear()

        self.seen_invites.clear()

        QMessageBox.information(
            self, "Disconnect", "Disconnect with session. You can continue working locally."
        )

    def _handle_peer_leave(self, msg):
        """Handle a peer leaving the session."""
        peer_id = msg.get("from_id")
        if peer_id in self.peers:
            peer_name = self.peers[peer_id]["name"]
            del self.peers[peer_id]

            QMessageBox.information(self, "Info", f"{peer_name} leaved session.")

    def _handle_peer_announce(self, msg):
        """Handle incoming peer announcement and connect to the new peer."""
        p_id = msg["peer_id"]
        if p_id == self.client_id:
            return
        if p_id in self.peers:
            return

        self._add_peer(p_id, msg["peer_ip"], msg["peer_port"], msg["peer_name"])

    def _send_peer_announce(
        self, target_ip, target_port, peer_id, peer_name, peer_ip, peer_port
    ):
        """Send a PEER_ANNOUNCE message to a specific target."""
        msg = {
            "type": "PEER_ANNOUNCE",
            "peer_id": peer_id,
            "peer_name": peer_name,
            "peer_ip": peer_ip,
            "peer_port": peer_port,
        }
        payload = json.dumps(msg).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (target_ip, target_port))

    def _add_peer(self, peer_id, ip, port, name):
        self.peers[peer_id] = {
            "ip": ip,
            "port": port,
            "name": name,
            "last_seen": time.time(),
        }
        print(f"[PEER] Dodano {name} ({ip}:{port})")

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
            "node_count": node_count,
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
            return

        print(
            f"[SYNC] Inconsistency detected with {sender_id}. Me: {my_count} nodes, Them: {remote_count} nodes."
        )

        if my_count > remote_count:
            print(f"[SYNC] Sending snapshot to {sender_id} (I have more data).")
            self._send_snapshot_to_peer(sender_id)
        elif my_count < remote_count:
            print(f"[SYNC] Requesting snapshot from {sender_id} (They have more data).")
            self._request_snapshot(sender_id)
        else:
            if self.client_id > sender_id:
                print(f"[SYNC] Tie-break: Sending snapshot to {sender_id}.")
                self._send_snapshot_to_peer(sender_id)
            else:
                pass

    def _request_snapshot(self, peer_id):
        """Send a request for a snapshot to a specific peer."""
        peer = self.peers.get(peer_id)
        if not peer:
            return

        msg = {"type": "REQUEST_SNAPSHOT", "from_id": self.client_id}
        payload = json.dumps(msg).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (peer["ip"], peer["port"]))

    def get_shared_file(self):
        def listen():
            self.auto_select_ip()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("", self.user.port_listen))
            print(f"[UDP] Listening on {self.user.port_listen} ...")
            while True:
                try:
                    data, addr = sock.recvfrom(65535)

                    try:
                        decompressed = gzip.decompress(data)
                        data = decompressed
                    except (gzip.BadGzipFile, OSError):
                        pass

                    msg = json.loads(data.decode("utf-8"))

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

        self._ensure_crdt_synced()
        self.invite_id = str(uuid.uuid4())
        msg = {
            "type": "INVITE",
            "invite_id": self.invite_id,
            "from_id": self.client_id,
            "from_name": self.user_name,
            "listen_port": self.user.port_listen,
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
        QMessageBox.information(
            self, "Share", "Inivitation sent. Waiting for responses."
        )

    def _on_key(self, e):
        """Handle key events for broadcasting CRDT inserts/deletes (Qt version)."""
        if self.applying_remote or e is None:
            return

        self._update_cursor_node_from_position()

        cursor = self.text.textCursor()
        index = cursor.position()

        if (
            e.modifiers() & Qt.KeyboardModifier.ControlModifier
        ) and e.key() == Qt.Key.Key_V:
            clipboard = QApplication.clipboard()
            if clipboard:
                text = clipboard.text()
                if text:
                    self._broadcast_insert(index, text)
                    self._sync_text_from_crdt()
                    self._move_cursor(self._get_cursor_position_from_node())
            return

        if e.key() == Qt.Key.Key_Backspace:
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                self._broadcast_delete_range(start, end)
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
                return
            else:
                if index > 0:
                    self._broadcast_delete(index)
                    self._sync_text_from_crdt()
                    self._move_cursor(self._get_cursor_position_from_node())
                return

        elif e.key() == Qt.Key.Key_Delete:
            if cursor.hasSelection():
                start = cursor.selectionStart()
                end = cursor.selectionEnd()
                self._broadcast_delete_range(start, end)
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
                return
            else:
                if index < len(self.text.toPlainText()):
                    self._broadcast_delete(index + 1)
                    self._sync_text_from_crdt()
                    self._move_cursor(self._get_cursor_position_from_node())
                return

        elif e.key() == Qt.Key.Key_Return:
            self._broadcast_insert(index, "\n")
            self._sync_text_from_crdt()
            self._move_cursor(self._get_cursor_position_from_node())
            return

        elif e.text():
            if e.text() >= " ":
                self._broadcast_insert(index, e.text())
                self._sync_text_from_crdt()
                self._move_cursor(self._get_cursor_position_from_node())
                return

        QTextEdit.keyPressEvent(self.text, e)
        self._update_cursor_node_from_position()

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

        for i, node_id in enumerate(id_map):
            if node_id == self.cursor_node:
                return i + 1

        current_id = self.cursor_node
        while current_id != HEAD:
            if current_id not in self.crdt.nodes:
                current_id = HEAD
                break

            node = self.crdt.nodes[current_id]
            if not node.deleted:
                for i, visible_id in enumerate(id_map):
                    if visible_id == current_id:
                        return i + 1

            current_id = node.after

        return 0

    def _broadcast_insert(self, index, text):
        """Broadcast CRDT insert operations for each character."""

        after_id = self.cursor_node

        for ch in text:
            node_id = self.next_op_id()
            self.crdt.apply_insert(after_id, node_id, ch)
            print(f"[CRDT] LOCAL INSERT: '{ch}' node={node_id} after={after_id}")
            op = {
                "type": "CRDT_INSERT",
                "after": list(after_id) if isinstance(after_id, tuple) else after_id,
                "node_id": list(node_id),
                "char": ch,
            }
            self._send_to_peers(op)
            after_id = node_id

        self.cursor_node = after_id

    def _broadcast_delete(self, index):
        """Broadcast a CRDT delete operation."""
        id_map = self._get_visible_id_map()
        if index < 1 or index > len(id_map):
            return
        node_id = id_map[index - 1]

        self.cursor_node = id_map[index - 2] if index >= 2 else HEAD
        self.crdt.apply_delete(node_id)
        op = {
            "type": "CRDT_DELETE",
            "node_id": list(node_id) if isinstance(node_id, tuple) else node_id,
        }
        self._send_to_peers(op)

    def _broadcast_delete_range(self, start, end):
        """Broadcast CRDT delete operations for a range of characters."""
        id_map = self._get_visible_id_map()
        if start < 0 or end > len(id_map):
            return

        self.cursor_node = id_map[start - 1] if start >= 1 else HEAD

        node_ids = [id_map[i] for i in range(start, end)]
        for node_id in node_ids:
            self.crdt.apply_delete(node_id)
            op = {
                "type": "CRDT_DELETE",
                "node_id": list(node_id) if isinstance(node_id, tuple) else node_id,
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

        self._update_lamport_clock(node_id[0])

        if self.crdt.apply_insert(after, node_id, char):
            print(f"[CRDT] INSERT OK: '{char}' node={node_id} after={after}")
            self._flush_pending_ops()
            self._sync_text_from_crdt()
        else:
            print(
                f"[CRDT] INSERT PENDING: '{char}' node={node_id} after={after} (after not found)"
            )
            self.pending_ops.append(("insert", after, node_id, char))

    def _apply_remote_delete(self, msg):
        """Apply a remote delete operation using CRDT."""
        node_id = tuple(msg["node_id"])

        if self.crdt.apply_delete(node_id):
            print(f"[CRDT] DELETE OK: node={node_id}")
            self._sync_text_from_crdt()
        else:
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
            new_text = self.crdt.render()
            current_text = self.text.toPlainText()

            if new_text != current_text:
                self.text.setPlainText(new_text)

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
        print(
            f"[CRDT] SNAPSHOT SEND to {peer['name']}: {len(crdt_dict.get('nodes', []))} nodes"
        )

        msg = {
            "type": "SNAPSHOT",
            "from_id": self.client_id,
            "from_name": self.user_name,
            "crdt_state": crdt_dict,
        }

        payload = json.dumps(msg).encode("utf-8")

        payload = gzip.compress(payload)

        self._send_udp_payload(payload, peer["ip"], peer["port"])

    def _send_udp_payload(self, payload, ip, port):
        """Send data via UDP, fragmenting if necessary."""
        MAX_SIZE = 32000

        if len(payload) <= MAX_SIZE:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload, (ip, port))
        else:
            msg_id = str(uuid.uuid4())
            total_chunks = (len(payload) + MAX_SIZE - 1) // MAX_SIZE

            print(
                f"[CHUNK] Splitting {len(payload)} bytes into {total_chunks} chunks for {ip}"
            )

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                for i in range(total_chunks):
                    chunk = payload[i * MAX_SIZE : (i + 1) * MAX_SIZE]
                    chunk_b64 = base64.b64encode(chunk).decode("ascii")

                    packet = {
                        "type": "CHUNK",
                        "id": msg_id,
                        "i": i,
                        "n": total_chunks,
                        "data": chunk_b64,
                        "from_id": self.client_id,
                    }

                    packet_bytes = json.dumps(packet).encode("utf-8")
                    try:
                        sock.sendto(packet_bytes, (ip, port))

                        time.sleep(0.002)
                    except OSError as e:
                        print(f"[CHUNK] Send error: {e}")

    def _prompt_unsaved_before_join(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Niezapisane zmiany")
        msg.setText(
            "Masz niezapisane zmiany.\n"
            "Dołączenie do sesji nadpisze bieżącą zawartość.\n"
            "Co robimy?"
        )

        save_btn = msg.addButton("Zapisz zmiany", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton(
            "Odrzuć zmiany", QMessageBox.ButtonRole.DestructiveRole
        )
        msg.addButton("Anuluj", QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        clicked = msg.clickedButton()
        if clicked == save_btn:
            return "save"
        elif clicked == discard_btn:
            return "discard"
        return "cancel"

    def eventFilter(self, obj, event):
        if obj is self.text and event.type() == event.Type.KeyPress:
            self._on_key(event)
            return True
        return super().eventFilter(obj, event)

class User:
    """Network configuration for sending and receiving UDP messages."""

    def __init__(self, port_listen_=5005, port_send_=5010):
        """
        Initialize a User network object.

        Args:
            port_listen_ (int): UDP port to listen for incoming messages.
            port_send_ (int): UDP port to send outgoing messages.
        """
        self.host = ""
        self.port_listen = port_listen_
        self.port_send = port_send_
        self.bcast = "255.255.255.255"
