from concurrency import ConcurrentTextEditor
from PyQt6.QtWidgets import QApplication
import sys


def main():
    app = QApplication(sys.argv)
    editor = ConcurrentTextEditor()
    editor.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
