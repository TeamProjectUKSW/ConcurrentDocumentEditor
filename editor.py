import tkinter as tk # for GUI
from tkinter import filedialog, messagebox # for creating and saving editor window
import concurrency

class SimpleTextEditor:
    """
    A text editor main class with basic functionality: opening, saving, editing,
    and inserting text. Uses Tkinter as the GUI framework.

    Attributes:
        root (tk.Tk): The main application window.
        current_file_path (str or None): Path to the currently opened/saved file.
        con(Concurrency): Object to handling multiuser features
        text (tk.Text): The text widget used for editing.
    """
    def __init__(self, root_):
        """
        Initialize the text editor window, toolbar, buttons, and text area.

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
        Updates the window title to display the opened file path.
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
        If no file is currently open, show a dialog asking for a save location.
        Displays a message box when saving is complete.
        """
        if self.current_file_path is None:
            file_path = filedialog.asksaveasfilename(
                title="Save file",
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            if not file_path:
                return
            self.current_file_path = file_path

        content = self.text.get("1.0", tk.END) # writes all text from tk widget to content variable
        with open(self.current_file_path, "w", encoding="utf-8") as f: # writing to the txt file
            f.write(content)

        messagebox.showinfo("Saved", f"File saved as:\n{self.current_file_path}")
        self.root.title(f"Text editor - {self.current_file_path}")

    #  PLACEHOLDER
    def share(self):
        """
        Placeholder function for sharing files functionality.
        Shares user's file to other users in order to work with the same document.
        """
        messagebox.showinfo("Share", "File sharing in progress...")
        content = self.text.get("1.0", tk.END).strip()
        self.con.share_file(content)

    #TEST
    def insert_test_text(self):
        """
        Insert a test message at the end of the text field and scroll to the bottom.
        Useful for simulating incoming messages or collaboration features.
        """
        self.text.insert("end", "Hello world!")
        self.text.see("end")
    #

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("800x600") # mozna zmieniac poczatkowy rozmiar okna
    app = SimpleTextEditor(root)
    root.mainloop()
