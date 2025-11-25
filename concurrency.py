import socket
from tkinter import messagebox
import threading
import editor
import netifaces
import psutil

def get_local_ip():
    for interface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                ip = addr.address
                # Pomijamy loopback i APIPA
                if not ip.startswith("169.") and not ip.startswith("127."):
                    return ip
    return None


def get_all_local_ips():
    ips = []
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
        for addr in addrs:
            ip = addr['addr']
            if ip != "127.0.0.1":  # tylko loopback odrzucamy
                ips.append(ip)
    return ips



class Concurrency(object):
    def __init__(self, port_ = 5005, port_send_ = 5010, root = None, editor_ = None):
        self.root = root
        self.editor = editor_ if editor_ else editor.SimpleTextEditor(self.root)
        self.port = port_
        self.port_send = port_send_
        hostname = socket.gethostname()
        ips = socket.gethostbyname_ex(hostname)[2]
        print("Dostępne IP kart sieciowych:")
        print("\n".join(ips))
        self.host = input("Podaj ip swojej karty - tej w  sieci: ")
        print("Local IP:", self.host)


    def ask_to_load_file(self, data):
        answer = messagebox.askyesno("Load File", "Do you want to load file from other user?")
        if answer:
            print("Loading file...")
            self.editor.text.delete("1.0", "end")
            self.editor.text.insert("end", data)
            self.editor.text.see("end")
        else:
            print("Refusing to load file")

    def get_shared_file(self):
        local_ips = get_all_local_ips()
        def listen():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.host, self.port))
            print(f"Listening UDP on {self.host}:{self.port} ...")

            while True:
                data, addr = sock.recvfrom(1024)
                print("Moje wszystkie karty sieciowe: ", local_ips)
                print("Moj IP: ", self.host)
                print("Adres,z którego odbieram dane: ", addr[0])
                if addr[0] in local_ips:
                    continue
                print(f"Received from {addr}: {data.decode('utf-8')}")
                file_content = data.decode("utf-8")
                self.root.after(0, lambda cnt=file_content: self.ask_to_load_file(cnt))
        threading.Thread(target=listen, daemon=True).start()

    def share_file(self, text):
        def send_file_content():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                print("!", self.host)
                sock.bind(('', self.port_send))
                bcast = input("Wpisz bcast sieci: ")
                sock.sendto(text.encode('utf-8'), (bcast, self.port))
                print(f"Wysłano broadcast: {text}")
                print(sock.getsockname()[0])
        send_file_content()



