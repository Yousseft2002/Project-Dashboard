"""Start Project Tracker and open it in the browser.

Double-click "Project Tracker" on the desktop, or run:  python run.py
If it is already running, this just opens the browser tab.
"""
import logging
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    from tracker.github_dashboard import serve
    hostname = os.environ.get("PUBLIC_HOSTNAME") or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    try:
        httpd = serve(PORT, host=HOST, production=PRODUCTION, expected_host=hostname)
    except OSError:
        sys.exit(f'Port {PORT} is unavailable. Stop the old tracker or configure PORT and APP_ORIGIN for a different port.')
    print(f"Project Tracker ({APP_ENV}) listening on {HOST}:{PORT}" + (f" · {hostname}" if hostname else ""))
    if not PRODUCTION and "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
