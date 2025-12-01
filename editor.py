import tkinter as tk # for GUI
from tkinter import filedialog, messagebox # for creating and saving editor window
import concurrency
import os

class SimpleTextEditor:
    """
    A basic text editor application with features for opening, editing,
    saving, and sharing text files. It also supports multi-user collaboration
    through networking, using the Concurrency class.

    Attributes:
        root (tk.Tk): The main application window.
        current_file_path (str or None): Path to the currently opened or saved file.
        con (Concurrency): Object handling file sharing and multiuser features.
        text (tk.Text): The text widget used for content editing.
    """
    def __init__(self, root_):
        """
        Initialize the text editor window, toolbar, buttons, and text area.

        Sets up buttons for file operations (open, save, share), adds
        a test button for demonstration, and initializes the text area
        with scrollbar support. Also starts a listener for receiving
        shared files over the network.

        Args:
            root_ (tk.Tk): The main Tkinter window passed to the editor.
        """
        self.root = root_ # main tkinter window
        self.root.title("Text editor") # title the window
        self.current_file_path = None # path to currently editing text file if such a file was opened in editor


        # toolbar
        toolbar = tk.Frame(self.root) # creates a frame for e.x. buttons
        toolbar.pack(side=tk.TOP, fill=tk.X) # puts this frame at the top of the window

        #  buttons
        # tk.Button - creates a certain button at the toolbar
        # command=self is a function that is called after pressing the button
        # .pack(side... ) - puts the bottoms in right places and puts gaps between them
        btn_open = tk.Button(toolbar, text="Open", command=self.open_file)
        btn_open.pack(side=tk.LEFT, padx=2, pady=2)

        btn_save = tk.Button(toolbar, text="Save", command=self.save_file)
        btn_save.pack(side=tk.LEFT, padx=2, pady=2)

        btn_save = tk.Button(toolbar, text="Save as", command=self.saveas_file)
        btn_save.pack(side=tk.LEFT, padx=2, pady=2)

        btn_share = tk.Button(toolbar, text="Share", command=self.share)
        btn_share.pack(side=tk.LEFT, padx=2, pady=2)

        #test
        btn_test = tk.Button(toolbar, text="Add test", command=self.insert_test_text)
        btn_test.pack(side=tk.LEFT, padx=2, pady=2)

        # text field
        text_frame = tk.Frame(self.root)
        text_frame.pack(fill=tk.BOTH, expand=True)

        # undo=true enables to use ctrl + z
        # ctrl+c,v,x work by default
        # wrap="word" automatically put words at the next line after reahing the end of the text window
        self.text = tk.Text(text_frame, wrap="word", undo=True)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # creates vertical scrollbar
        scrollbar = tk.Scrollbar(text_frame, command=self.text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.config(yscrollcommand=scrollbar.set) # updates the scrollbar position

        self.con = concurrency.Concurrency(port_=5005, port_send_=5010, root=self.root, editor_=self)
        self.con.get_shared_file()  # starts listening to other users if they want to share file

    def open_file(self):
        """
        Open a text file using a file dialog and load its contents into the editor.

        Allows user to choose a file via a dialog. If a file is selected,
        reads its content and places it into the text widget, replacing any
        existing text. Also updates the window title to show the file path.
        """
        file_path = filedialog.askopenfilename(
            title="Open file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not file_path:
            return

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.current_file_path = file_path
        self.root.title(f"Text editor - {file_path}")

    def save_file(self):
        """
        Save the current text to a file.

        Opens a 'Save As'
        dialog to let the user choose a location and file name. After saving,
        updates the window title and confirms success with a message box.
        """
        content = self.text.get("1.0", tk.END) # writes all text from tk widget to content variable
        with open(self.current_file_path, "w", encoding="utf-8") as f: # writing to the txt file
            f.write(content)

        messagebox.showinfo("Saved", f"File saved:\n{self.current_file_path}")
        self.root.title(f"Text editor - {self.current_file_path}")

    def saveas_file(self):
        """
        Open a 'Save As' dialog to allow the user to choose a location and name
        for saving the current text content to a new file.

        If the selected path does not exist (e.g. user enters a non-existing folder),
        an error message is shown and the saving process is aborted.

        When a valid path is selected, the content of the text editor is written
        to the chosen file, updates the window title, and displays a confirmation message.

        Returns:
            None
        """
        file_path = filedialog.asksaveasfilename(
            title="Save file",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not os.path.exists(os.path.dirname(file_path)):  # when user wants to save file in not existing directory
            messagebox.showerror("Error", "Path does not exist!")
            return
        self.current_file_path = file_path
        content = self.text.get("1.0", tk.END)  # writes all text from tk widget to content variable
        with open(self.current_file_path, "w", encoding="utf-8") as f:  # writing to the txt file
            f.write(content)

        messagebox.showinfo("Saved", f"File saved as:\n{self.current_file_path}")
        self.root.title(f"Text editor - {self.current_file_path}")

    def share(self):
        """
        Share the current file content with other users in the same network.

        Retrieves the full text from the editor and sends it via UDP broadcast
        using the Concurrency class, enabling collaborative editing between users.
        Displays a notification to indicate that the sharing process has started.

        Note:
            The receiving users will be asked whether they want to load the file.
        """
        messagebox.showinfo("Share", "File sharing in progress...")
        content = self.text.get("1.0", tk.END).strip()
        self.con.share_file(content)

    #TEST
    def insert_test_text(self):
        """
        Insert sample text at the end of the document.

        Useful for demonstration or testing collaboration features.
        Automatically scrolls to the bottom of the editor after insertion.
        """
        self.text.insert("end", "Hello world!")
        self.text.see("end")

def main():
    root = tk.Tk()
    root.geometry("800x600")  # mozna zmieniac poczatkowy rozmiar okna
    SimpleTextEditor(root)
    root.mainloop()
    # user1 = concurrency.User(root)
    # user1.start_text_monitoring()
    # user1.monitor_text_changes()

if __name__ == "__main__":
    main()
