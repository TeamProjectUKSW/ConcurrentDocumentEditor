from concurrency import ConcurrentTextEditor
import sys

def main():
    app = ConcurrentTextEditor()
    app.run()

if __name__ == "__main__":
    sys.exit(main())