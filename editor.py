from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QFontDialog,
    QComboBox
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

        #Layouts
        main_layout = QVBoxLayout()
        toolbar_layout = QHBoxLayout()
        main_layout.addLayout(toolbar_layout)
        self.setLayout(main_layout)

        #buttons
        toolbar_layout.addWidget(self._btn("Open", self.open_file))
        toolbar_layout.addWidget(self._btn("Save", self.save_file))
        toolbar_layout.addWidget(self._btn("Save as", self.saveas_file))
        toolbar_layout.addWidget(self._btn("Share", self.share_file))
        toolbar_layout.addWidget(self._btn("Disconnect", self.leave_session))
        toolbar_layout.addWidget(self._btn("Change font", self.change_font))

        #themes
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([
            "Standard Light",
            "Warm Cream",
            "Dark Grey",
            "Midnight Blue",
            "Terminal Rose",
            "Deep Charcoal",
        ])
        self.theme_combo.currentIndexChanged.connect(self.switch_theme)
        toolbar_layout.addWidget(self.theme_combo)

        #text editor
        self.text = QTextEdit()
        self.text.setAcceptRichText(False)
        self.text.textChanged.connect(self._on_modified)
        main_layout.addWidget(self.text)

        #theme initialisation
        self.set_light_theme()

    #help methods
    def _btn(self, label, slot):
        """
        Create a toolbar button with the given label and callback.

        Args:
            label (str): Text displayed on the button.
            slot (callable): Function to be called when the button is clicked.

        Returns:
            QPushButton: Configured button instance.
        """
        btn = QPushButton(label)
        btn.clicked.connect(slot)
        return btn

    #themes methods
    def set_light_theme(self):
        """
        Apply the standard light theme.

        Uses a bright background with dark text, suitable for daytime use
        and general-purpose text editing.
        """
        self.setStyleSheet("""
            QWidget { background-color: #f9f9f9; color: #1e1e1e; }
            QTextEdit { background-color: #ffffff; color: #000000; border: 1px solid #cccccc; }
            QPushButton, QComboBox { background-color: #e0e0e0; color: #1e1e1e; border-radius: 4px; padding: 5px; }
            QPushButton:hover, QComboBox:hover { background-color: #d0d0d0; }
        """)

    def set_cream_theme(self):
        """
        Apply a warm cream-colored theme.

        Designed to reduce eye strain during long writing sessions by using
        softer background colors and lower contrast.
        """
        self.setStyleSheet("""
            QWidget { background-color: #fff8e7; color: #3b3b3b; }
            QTextEdit { background-color: #fffdf4; color: #2b2b2b; border: 1px solid #e6dabe; }
            QPushButton, QComboBox { background-color: #f0e6d2; color: #3b3b3b; border-radius: 4px; padding: 5px; }
            QPushButton:hover, QComboBox:hover { background-color: #e6dabe; }
        """)

    def set_dark_grey_theme(self):
        """
        Apply a classic dark grey theme.

        Suitable for low-light environments and users who prefer a traditional
        dark editor appearance.
        """
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #f0f0f0; }
            QTextEdit { background-color: #3c3f41; color: #f0f0f0; border: 1px solid #555; }
            QPushButton, QComboBox { background-color: #505357; color: #f0f0f0; border-radius: 4px; padding: 5px; }
            QPushButton:hover, QComboBox:hover { background-color: #606367; }
        """)

    def set_midnight_theme(self):
        """
        Apply a midnight blue theme.

        Inspired by solarized and midnight-style color schemes, offering a calm,
        cool-toned dark interface for extended focus.
        """
        self.setStyleSheet("""
            QWidget { background-color: #0f1f2c; color: #d0e0f0; }
            QTextEdit { background-color: #162a3b; color: #e6f2ff; border: 1px solid #2a4d69; }
            QPushButton, QComboBox { background-color: #1c3b57; color: #d0e0f0; border-radius: 4px; padding: 5px; }
            QPushButton:hover, QComboBox:hover { background-color: #264d70; }
        """)

    def set_terminal_theme(self):
        """
        Apply a soft rose terminal-style theme.

        Uses a dark background with muted rose-colored text, inspired by
        retro terminals and modern dusk-style color palettes.
        """
        self.setStyleSheet("""
            QWidget {
                background-color: #141216;
                color: #d8a1b5;
            }

            QTextEdit {
                background-color: #1a161c;
                color: #e2b4c3;
                border: 1px solid #3a2a34;
                font-family: Consolas, Menlo, Monaco, monospace;
            }

            QPushButton, QComboBox {
                background-color: #211b22;
                color: #d8a1b5;
                border: 1px solid #4a3440;
                border-radius: 4px;
                padding: 5px;
            }

            QPushButton:hover, QComboBox:hover {
                background-color: #2c2330;
            }
        """)

    def set_charcoal_theme(self):
        """
        Apply a deep charcoal theme.

        Provides very high contrast and minimal distraction, optimized for
        users who prefer an extremely dark interface.
        """
        self.setStyleSheet("""
            QWidget { background-color: #121212; color: #e0e0e0; }
            QTextEdit { background-color: #1e1e1e; color: #ffffff; border: 1px solid #333; }
            QPushButton, QComboBox { background-color: #333333; color: #ffffff; border-radius: 4px; padding: 5px; }
            QPushButton:hover, QComboBox:hover { background-color: #444444; }
        """)

    def switch_theme(self, index):
        """Switch theme based on the combo box index."""
        if index == 0:
            self.set_light_theme()
        elif index == 1:
            self.set_cream_theme()
        elif index == 2:
            self.set_dark_grey_theme()
        elif index == 3:
            self.set_midnight_theme()
        elif index == 4:
            self.set_terminal_theme()
        elif index == 5:
            self.set_charcoal_theme()

    #editor methods
    def change_font(self):
        """
        Open a font selection dialog and apply the selected font to the editor.
        """
        font, ok = QFontDialog.getFont()
        if ok:
            self.text.setFont(font)

    def _on_modified(self):
        """Mark the document as modified whenever text changes."""
        self.is_dirty = True

    def open_file(self):
        """
        Open a text file using a file dialog and load its content into the editor.
        Sets the window title and clears the dirty flag.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open file", "", "Text files (*.txt);;All files (*)"
        )
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
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save file", "", "Text files (*.txt);;All files (*)"
        )
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
        QMessageBox.information(
            self, "Saved", f"File saved as:\n{self.current_file_path}"
        )
        self.is_dirty = False
        self.setWindowTitle(f"Text editor - {self.current_file_path}")

    # def insert_test_text(self):
    #     """Insert sample text at the end of the editor."""
    #     self.text.append("Hello world!")

    def share_file(self):
        """
        Placeholder for file sharing logic.
        In the base editor, this method does nothing.
        """
        pass

    def leave_session(self):
        """
        Disconnect from a collaborative session.

        Base implementation does nothing.
        Subclasses may override this to provide custom behavior.
        """
        pass
