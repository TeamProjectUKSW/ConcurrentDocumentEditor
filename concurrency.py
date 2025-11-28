import socket
from tkinter import messagebox
import tkinter as tk
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
    ips = dict()
    for iface in netifaces.interfaces():
        addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
        for addr in addrs:
            ip = addr.get('addr')
            broadcast = addr.get('broadcast')
            if ip != "127.0.0.1" and not ip.startswith("169.254."):
                ips[ip] = broadcast
    return ips



class Concurrency(object):
    def __init__(self, port_ = 5005, port_send_ = 5010, root = None, editor_ = None):
        self.root = root
        self.editor = editor_ if editor_ else editor.SimpleTextEditor(self.root)
        self.port = port_
        self.port_send = port_send_
        self.host = ''

    def select_ip_gui(self):
        def confirm_selection():
            nonlocal selected_ip
            nonlocal selected_bcast
            selection = listbox.curselection()
            if selection:
                selected_ip = listbox.get(selection[0])
                selected_bcast = ip_dict[selected_ip]
                popup.destroy()
                self.root.deiconify()
                self.root.lift()
                self.root.attributes('-topmost', True)
                self.root.after(100, lambda: self.root.attributes('-topmost', False))
            if not selection:
                raise Exception("Please choose one IP")

        hostname = socket.gethostname()
        ip_dict = get_all_local_ips()
        selected_ip = '' # poprawic!!!
        selected_bcast = ''  # poprawic!!!
        popup = tk.Toplevel(self.root)
        popup.title("Choose IP of inet interface")
        popup.grab_set()
        popup.attributes('-topmost', True) # at the top, not hidden window
        popup.update_idletasks() # in the middle
        tk.Label(popup, text="Choose IP:").pack(pady=5)
        listbox = tk.Listbox(popup, height=len(ip_dict), selectmode=tk.SINGLE)
        for ip in ip_dict.keys():
            listbox.insert(tk.END, ip)
        listbox.pack(padx=10, pady=10)
        tk.Button(popup, text="OK", command=confirm_selection).pack(pady=10)
        popup.wait_window()
        self.host = selected_ip
        return {selected_ip:selected_bcast}

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
                print("Address from which received data: ", addr[0])
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
                sock.bind(('', self.port_send))
                bcast = next(iter(self.select_ip_gui().values()))
                print("Bcast:", bcast)
                sock.sendto(text.encode('utf-8'), (bcast, self.port))
                print(f"Bcast sent: {text}")
        send_file_content()



