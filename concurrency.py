import socket
from tkinter import messagebox
import tkinter as tk
import threading
from editor import BaseTextEditor
import netifaces
import time
import json
import uuid


def get_all_local_ips():
    """
    Retrieve all local IPv4 addresses and their broadcast addresses.

    Scans available network interfaces and collects valid local IP addresses
    along with their broadcast addresses. Filters out loopback and APIPA addresses.

    Returns:
        dict: A dictionary where keys are local IP addresses (str) and values
              are corresponding broadcast addresses (str).
              Example: {"192.168.1.10": "192.168.1.255"}

    Raises:
        Exception: If no valid IP addresses are found.
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



class ConcurrentTextEditor(BaseTextEditor):
    """
    A class to enable concurrent file sharing between users via UDP broadcasting.

    This class handles network configuration, GUI interface for IP selection,
    listening for incoming files, and sending/shared files over the network.

    Attributes:
        root (Tk): Tkinter root window.    """
    def __init__(self):
        """
        Initialize the Concurrency instance.

        """
        super().__init__()

        self.user = User(port_listen_=5005, port_send_=5010)

        self.client_id = str(uuid.uuid4())[:8]
        self.user_name = self.client_id
        self.peers = {}
        self.crdt_counter = 0
        self.applying_remote = False


        self.get_shared_file()

        self.last_notified_length = 0  # remembered characters number
        self.start_text_monitoring()  # begin monitoringu
        self.text.bind("<Key>", self._on_key)

    def run(self):
        self.root.mainloop()


    def _handle_invite(self, msg, addr):
        if msg["from_id"] == self.client_id:
            return  #

        def ask():
            ok = messagebox.askyesno(
                "Share request",
                f"{msg['from_name']} chce współdzielić dokument.\nAkceptujesz?"
            )
            if ok:
                peer_ip = addr[0]
                peer_port = msg["listen_port"]

                self._add_peer(msg["from_id"], peer_ip, peer_port, msg["from_name"])

                response = {
                    "type": "INVITE_ACCEPT",
                    "from_id": self.client_id,
                    "from_name": self.user_name,
                    "listen_port": self.user.port_listen
                }

                payload = json.dumps(response).encode("utf-8")
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(payload, (peer_ip, peer_port))

        self.root.after(0, ask)

    def _handle_invite_accept(self, msg, addr):
        peer_ip = addr[0]
        peer_port = msg["listen_port"]

        self._add_peer(msg["from_id"], peer_ip, peer_port, msg["from_name"])

        messagebox.showinfo(
            "Share",
            f"{msg['from_name']} dołączył do sesji."
        )


    def _handle_message(self, msg, addr):

        if msg.get("from_id") == self.client_id:
            return

        print(f"[RECV] from={addr} type={msg.get('type')} from_id={msg.get('from_id')} from_name={msg.get('from_name')}")
        print(f"[ME]   my_id={self.client_id} my_name={self.user_name}")


        msg_type = msg.get("type")

        if msg_type == "INVITE":
            self._handle_invite(msg, addr)

        elif msg_type == "INVITE_ACCEPT":
            self._handle_invite_accept(msg, addr)

        elif msg_type == "CRDT_INSERT":
            self._apply_remote_insert(msg)

        elif msg_type == "CRDT_DELETE":
            self._apply_remote_delete(msg)



    def _add_peer(self, peer_id, ip, port, name):
        self.peers[peer_id] = {
            "ip": ip,
            "port": port,
            "name": name,
            "last_seen": time.time()
        }
        print(f"[PEER] Dodano {name} ({ip}:{port})")


    def auto_select_ip(self):
        ips = get_all_local_ips()
        ip, bcast = next(iter(ips.items()))
        self.user.host = ip
        self.user.bcast = bcast
        print(f"[NET] Using {ip} / {bcast}")
    
    def next_op_id(self):
        self.crdt_counter += 1
        return (self.crdt_counter, self.client_id)
    
    def _broadcast_insert(self, index, char):
        op = {
            "type": "CRDT_INSERT",
            "id": self.next_op_id(),
            "index": index,
            "char": char
        }
        self._send_to_peers(op)
    
    def _broadcast_delete(self, index):
        op = {
            "type": "CRDT_DELETE",
            "id": self.next_op_id(),
            "index": index
        }
        self._send_to_peers(op)
    
    def _send_to_peers(self, msg):
        payload = json.dumps(msg).encode("utf-8")

        for peer in self.peers.values():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload, (peer["ip"], peer["port"]))
    
    def _apply_remote_insert(self, msg):
        self.applying_remote = True
        try:
            self.text.insert(msg["index"], msg["char"])
        finally:
            self.applying_remote = False
    
    def _apply_remote_delete(self, msg):
        self.applying_remote = True
        try:
            index = msg["index"]
            self.text.delete(f"{index}-1c")
        finally:
            self.applying_remote = False







    def get_shared_file(self):
        """
        Start a background thread to listen for incoming UDP messages (CRDT + INVITE).
        """
        def listen():
            # automatyczny wybór interfejsu
            self.auto_select_ip()

            ips = get_all_local_ips()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', self.user.port_listen))
            print(f"[UDP] Listening for INVITE on {self.user.port_listen} ...")

            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                except OSError as e:
                    print(f"[UDP ERROR] {e}")
                    return

                if addr[0] in ips:
                    continue

                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception as e:
                    print("[UDP] Invalid JSON:", e)
                    continue

                self.root.after(0, lambda m=msg, a=addr: self._handle_message(m, a))

        threading.Thread(target=listen, daemon=True).start()



    def share_file(self):
        msg = {
            "type": "INVITE",
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
                except Exception as e:
                    pass

        messagebox.showinfo("Share", "Zaproszenie wysłane. Czekam na odpowiedzi.")

    


    def start_text_monitoring(self):
        """Start a background thread to monitor text length."""
        thread = threading.Thread(target=self.monitor_text_changes, daemon=True)
        thread.start()

    def monitor_text_changes(self):
        """Monitor text widget and notify every time text grows by 10 new chars."""
        while True:
            content = self.text.get("1.0", tk.END).strip()
            current_length = len(content)

            if current_length >= self.last_notified_length + 10:
                self.last_notified_length = current_length
                self.root.after(0, lambda: messagebox.showinfo(
                    "Informacja", f"Wpisano {current_length} znaków!"
                ))
            time.sleep(1)  # sprawdzaj co 1 sekundę
    def _on_key(self, event):
        if self.applying_remote:
            return

        if event.char and event.char.isprintable():
            index = self.text.index(tk.INSERT)
            self._broadcast_insert(index, event.char)

        elif event.keysym == "BackSpace":
            index = self.text.index(tk.INSERT)
            self._broadcast_delete(index)

class User(object):
    def __init__(self, port_listen_ = 5005, port_send_ = 5010):
        self.host = ''
        self.port_listen = port_listen_
        self.port_send = port_send_
        self.bcast = '255.255.255.255'










