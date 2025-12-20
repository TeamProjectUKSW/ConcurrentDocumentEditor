import socket
from tkinter import messagebox
import tkinter as tk
import threading
from editor import BaseTextEditor
import netifaces
import time
import json
import uuid
DISCOVERY_PORT = 4999


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

        self.get_shared_file()

        self.last_notified_length = 0  # remembered characters number
        self.start_text_monitoring()  # begin monitoringu

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
        msg_type = msg.get("type")

        if msg_type == "INVITE":
            self._handle_invite(msg, addr)

        elif msg_type == "INVITE_ACCEPT":
            self._handle_invite_accept(msg, addr)


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

    def get_shared_file(self):
        """
        Start a background thread to listen for incoming UDP messages (CRDT + INVITE).
        """
        def listen():
            # automatyczny wybór interfejsu
            self.auto_select_ip()

            ips = get_all_local_ips()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', DISCOVERY_PORT))
            print(f"[UDP] Listening for INVITE on {DISCOVERY_PORT} ...")

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

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, (self.user.bcast, self.user.port_listen))

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

class User(object):
    def __init__(self, port_listen_ = 5005, port_send_ = 5010):
        self.host = ''
        self.port_listen = port_listen_
        self.port_send = port_send_
        self.bcast = '255.255.255.255'










