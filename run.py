"""Start Project Tracker and open it in the browser.

Double-click "Project Tracker" on the desktop, or run:  python run.py
If it is already running, this just opens the browser tab.
"""
import socket
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
PORT = int(os.environ.get("PORT", "8765"))
if not 1 <= PORT <= 65535:
    raise ValueError("PORT must be between 1 and 65535")

PRODUCTION = APP_ENV == "production"
if APP_ENV not in ("development", "production"):
    raise ValueError("APP_ENV must be 'development' or 'production'")

HOST = "0.0.0.0" if PRODUCTION else "127.0.0.1"
URL = f"http://127.0.0.1:{PORT}/"


def already_running() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


if __name__ == "__main__":
    if not PRODUCTION and already_running():
        webbrowser.open(URL)
        sys.exit(0)
    from tracker.server import serve
    hostname = os.environ.get("PUBLIC_HOSTNAME") or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    httpd = serve(PORT, host=HOST, production=PRODUCTION, expected_host=hostname)
    print(f"Project Tracker ({APP_ENV}) listening on {HOST}:{PORT}" + (f" · {hostname}" if hostname else ""))
    if not PRODUCTION and "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
