import socket
from tkinter import messagebox
import tkinter as tk
import threading
from editor import BaseTextEditor
import netifaces
import time

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
        self.get_shared_file()  # starts listening to other users if they want to share file
        self.user = User(port_listen_ = 5005, port_send_ = 5010) # zmien na automatyczny wybor portow!!!
        self.last_notified_length = 0  # remembered characters number
        self.start_text_monitoring()  # begin monitoringu

    def run(self):
        self.root.mainloop()

    def select_ip_gui(self):
        """
        Display a GUI window for selecting a local IP address.

        Creates a popup window listing available local IP addresses. The user
        selects one, and the method assigns it as the host IP address.

        Returns:
            dict: A dictionary mapping the selected IP address to its broadcast address.
        """
        def confirm_selection():
            nonlocal selected_ip, selected_bcast
            selection = listbox.curselection()
            if not selection:  # nothing is selected
                messagebox.showerror("Error", "Please select an IP address")
                return  # dont closing the window
            selected_ip = listbox.get(selection[0])
            selected_bcast = ip_dict[selected_ip]
            popup.destroy()
            self.root.deiconify()
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False))

        def exiting():
            popup.destroy()
            self.root.deiconify()
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False))

        ip_dict = get_all_local_ips()
        selected_ip = ''
        selected_bcast = ''

        popup = tk.Toplevel(self.root)
        popup.title("Choose IP of internet interface")
        popup.grab_set()
        popup.attributes('-topmost', True)
        popup.update_idletasks()

        tk.Label(popup, text="Choose IP:").pack(pady=5)

        listbox = tk.Listbox(popup, height=len(ip_dict), selectmode=tk.SINGLE)
        for ip in ip_dict.keys():
            listbox.insert(tk.END, ip)
        listbox.pack(padx=10, pady=10)

        tk.Button(popup, text="OK", command=confirm_selection).pack(side=tk.LEFT, padx=10, pady=10)
        tk.Button(popup, text = "Exit", command = exiting).pack(side=tk.LEFT, padx=10, pady=10)

        popup.wait_window()
        self.user.host = selected_ip
        return {selected_ip: selected_bcast}

    def ask_to_load_file(self, data):
        """
        Prompt the user to load received file content.

        Displays a confirmation dialog asking if the user wants to load
        the incoming file content into the editor.

        Args:
            data (str): The text content to load into the editor.
        """
        answer = messagebox.askyesno("Load File", "Do you want to load file from other user?")
        if answer:
            print("Loading file...")
            self.root.text.delete("1.0", "end")
            self.root.text.insert("end", data)
            self.root.text.see("end")
        else:
            print("Refusing to load file")

    def get_shared_file(self):
        """
        Start a background thread to listen for incoming UDP file data.

        Opens a UDP socket on the specified listen port and continuously
        receives data. When data arrives, it triggers the GUI prompt to load
        the file content.
        """
        def listen():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.user.host, self.user.port_listen))
            print(f"Listening UDP on {self.user.host}:{self.user.port_listen} ...")

            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                except OSError as e:
                    print(f"Error: Check if shared file is less than maximum file size - 60kB: {e}")
                    return
                if addr[0] == self.user.host:
                    continue
                print(f"Received from {addr}: {data.decode('utf-8')}")
                file_content = data.decode("utf-8")
                self.root.after(0, lambda cnt=file_content: self.ask_to_load_file(cnt))
        threading.Thread(target=listen, daemon=True).start()

    def share_file(self):
        """
        Broadcast editor text content to other users via UDP.

        Opens a UDP socket with broadcast capability and sends file content
        to other local network users.
        """
        messagebox.showinfo("Share", "File sharing in progress...")
        text = self.text.get("1.0", tk.END).strip()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', self.user.port_send))
            bcast = next(iter(self.select_ip_gui().values()))
            print("Bcast:", bcast)
            sock.sendto(text.encode('utf-8'), (bcast, self.user.port_listen))
            sock.sendto(text.encode('utf-8'), (self.user.host[:8] + '255.255', self.user.port_listen))
            print(f"Bcast sent")

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










