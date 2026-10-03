"""Start Project Tracker and open it in the browser.

Double-click "Project Tracker" on the desktop, or run:  python run.py
If it is already running, this just opens the browser tab.
"""
import socket
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"


def already_running() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


if __name__ == "__main__":
    if already_running():
        webbrowser.open(URL)
        sys.exit(0)
    from tracker.server import serve
    httpd = serve(PORT)
    print(f"Project Tracker running at {URL}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
