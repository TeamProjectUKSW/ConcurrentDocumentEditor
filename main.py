from PyQt6.QtGui import QIcon
from concurrency import ConcurrentTextEditor
from PyQt6.QtWidgets import QApplication
import sys
import os
import ctypes

def main():
    if sys.platform.startswith("win") and not getattr(sys, "frozen", False):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "editor.concurrenttexteditor"
        )

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join("icon", "icon_256.png")))  # Path to the icon file
    editor = ConcurrentTextEditor()
    editor.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
