import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from fileorganizer.gui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
