from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QFontDialog
)
import os

class BaseTextEditor(QWidget):
    """
    A basic text editor implemented with PyQt6.

    Provides functionalities for opening, saving, editing text files, changing
    fonts, toggling themes, and inserting test text. Designed as a base class
    for more advanced editors with networking or CRDT support.

    Attributes:
        current_file_path (str | None): Path of the currently open file.
        is_dirty (bool): Flag indicating if the text has been modified.
        text (QTextEdit): Main text editing widget.
        theme_state (int): Current theme state (0=light, 1=dark, 2=cream, 3=mint).
    """
    def __init__(self):
        """Initialize the text editor, GUI components, and default theme."""
        super().__init__()
        self.setWindowTitle("Text editor")
        self.resize(800, 600)
        self.current_file_path = None
        self.is_dirty = False

        # Layout setup
        main_layout = QVBoxLayout()
        toolbar_layout = QHBoxLayout()
        main_layout.addLayout(toolbar_layout)
        self.setLayout(main_layout)

        # QTextEdit setup
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)  # plain text only
        self.text.textChanged.connect(self._on_modified)
        main_layout.addWidget(self.text)

        # Toolbar buttons
        btn_open = QPushButton("Open")
        btn_open.clicked.connect(self.open_file)
        toolbar_layout.addWidget(btn_open)

        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.save_file)
        toolbar_layout.addWidget(btn_save)

        btn_saveas = QPushButton("Save as")
        btn_saveas.clicked.connect(self.saveas_file)
        toolbar_layout.addWidget(btn_saveas)

        btn_share = QPushButton("Share")
        btn_share.clicked.connect(self.share_file)
        toolbar_layout.addWidget(btn_share)

        btn_test = QPushButton("Add test")
        btn_test.clicked.connect(self.insert_test_text)
        toolbar_layout.addWidget(btn_test)

        btn_font = QPushButton("Change font")
        btn_font.clicked.connect(self.change_font)
        toolbar_layout.addWidget(btn_font)

        btn_theme = QPushButton("Toggle theme")
        btn_theme.clicked.connect(self.toggle_theme)
        toolbar_layout.addWidget(btn_theme)

        # --- Default theme ---
        self.theme_state = 0  # 0=light, 1=dark, 2=cream, 3=mint
        self.set_light_theme()

    # Theme methods
    def set_light_theme(self):
        """Set a light, high-contrast theme for the editor."""
        self.setStyleSheet("""
            QWidget { background-color: #f9f9f9; color: #1e1e1e; }
            QTextEdit { background-color: #ffffff; color: #000000; }
            QPushButton { background-color: #e0e0e0; color: #1e1e1e; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #d0d0d0; }
        """)
        self.theme_state = 0

    def set_dark_theme(self):
        """Set a dark theme suitable for low-light environments."""
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #f0f0f0; }
            QTextEdit { background-color: #3c3f41; color: #f0f0f0; }
            QPushButton { background-color: #505357; color: #f0f0f0; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #606367; }
        """)
        self.theme_state = 1

    def set_cream_theme(self):
        """Set a warm cream theme that is easy on the eyes for reading text."""
        self.setStyleSheet("""
            QWidget { background-color: #fff8e7; color: #2e2e2e; }
            QTextEdit { background-color: #fffdf4; color: #1e1e1e; }
            QPushButton { background-color: #f0e6d2; color: #2e2e2e; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #e6dabe; }
        """)
        self.theme_state = 2

    def set_mint_theme(self):
        """Set a soft mint theme for a fresh and relaxing look."""
        self.setStyleSheet("""
            QWidget { background-color: #e6f7f1; color: #1e1e1e; }
            QTextEdit { background-color: #f0fcf9; color: #1e1e1e; }
            QPushButton { background-color: #ccebe1; color: #1e1e1e; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #b3ded2; }
        """)
        self.theme_state = 3

    def toggle_theme(self):
        """Cycle through available themes: light → dark → cream → mint → light."""
        if self.theme_state == 0:
            self.set_dark_theme()
        elif self.theme_state == 1:
            self.set_cream_theme()
        elif self.theme_state == 2:
            self.set_mint_theme()
        else:
            self.set_light_theme()

    #Font selection
    def change_font(self):
        """
        Open a font selection dialog and apply the selected font to the editor.
        """
        font, ok = QFontDialog.getFont()
        if ok:
            self.text.setFont(font)

    #File modification tracking
    def _on_modified(self):
        """Mark the document as modified whenever text changes."""
        self.is_dirty = True

    #File handling methods
    def open_file(self):
        """
        Open a text file using a file dialog and load its content into the editor.
        Sets the window title and clears the dirty flag.
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "Open file", "", "Text files (*.txt);;All files (*)")
        if not file_path:
            return
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.text.setPlainText(content)
        self.current_file_path = file_path
        self.setWindowTitle(f"Text editor - {file_path}")
        self.is_dirty = False

    def save_file(self):
        """
        Save the current file. If no file is set, open a Save As dialog.
        Shows a message box confirming save and resets dirty flag.
        """
        if not self.current_file_path:
            return self.saveas_file()
        content = self.text.toPlainText()
        with open(self.current_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        QMessageBox.information(self, "Saved", f"File saved:\n{self.current_file_path}")
        self.is_dirty = False
        self.setWindowTitle(f"Text editor - {self.current_file_path}")

    def saveas_file(self):
        """
        Open a Save As dialog and save the editor content to the selected path.
        Verifies that the directory exists and shows an error if not.
        """
        file_path, _ = QFileDialog.getSaveFileName(self, "Save file", "", "Text files (*.txt);;All files (*)")
        if not file_path:
            return
        dir_name = os.path.dirname(file_path)
        if dir_name and not os.path.exists(dir_name):
            QMessageBox.critical(self, "Error", "Path does not exist!")
            return
        self.current_file_path = file_path
        content = self.text.toPlainText()
        with open(self.current_file_path, "w", encoding="utf-8") as f:
            f.write(content)
        QMessageBox.information(self, "Saved", f"File saved as:\n{self.current_file_path}")
        self.is_dirty = False
        self.setWindowTitle(f"Text editor - {self.current_file_path}")

    # utility methods
    def insert_test_text(self):
        """Insert sample text at the end of the editor."""
        self.text.append("Hello world!")

    def share_file(self):
        """
        Placeholder for file sharing logic.
        In the base editor, this method does nothing.
        """
        pass
