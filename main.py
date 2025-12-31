from concurrency import ConcurrentTextEditor
from PyQt6.QtWidgets import QApplication
import sys


def main():
    app = QApplication(sys.argv)  # Tworzymy QApplication raz
    editor = ConcurrentTextEditor()
    editor.show()
    sys.exit(app.exec())  # uruchamiamy event loop


if __name__ == "__main__":
    main()