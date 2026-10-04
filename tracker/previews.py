"""Project preview screenshots via headless Edge/Chrome.

Sources, best first: the project's preview URL (e.g. a local dev server), its live URL, or a local HTML
entry point found by the scanner. Local files are served through a throwaway HTTP server so that
absolute asset paths like /static/style.css still resolve.
"""
from __future__ import annotations

import functools
import hashlib
import os
import shutil
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('TRACKER_DATA_DIR', str(ROOT / 'data')))
PREVIEWS = DATA / "previews"
PROFILE = DATA / "browser-profile"
DESKTOP = (1280, 800)
PHONE = (390, 844)
BLANKISH = 80_000  # bytes; a mostly blank 1280x800 PNG compresses below this


def find_browser() -> str | None:
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    local = os.environ.get("LOCALAPPDATA", "")
    for cand in (rf"{pf86}\Microsoft\Edge\Application\msedge.exe", rf"{pf}\Microsoft\Edge\Application\msedge.exe",
                 rf"{pf}\Google\Chrome\Application\chrome.exe", rf"{pf86}\Google\Chrome\Application\chrome.exe",
                 rf"{local}\Google\Chrome\Application\chrome.exe"):
        if cand and Path(cand).exists():
            return cand
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def preview_name(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def preview_path(key: str) -> Path:
    return PREVIEWS / f"{preview_name(key)}.png"


class _FallbackHandler(SimpleHTTPRequestHandler):
    """Static handler that maps /<mount>/file to file when the mount dir doesn't exist (e.g. FastAPI /static)."""

    def log_message(self, *args):
        pass

    def translate_path(self, path):
        full = super().translate_path(path)
        if os.path.exists(full):
            return full
        parts = [p for p in path.split("?", 1)[0].split("/") if p]
        for i in range(1, len(parts)):
            alt = super().translate_path("/" + "/".join(parts[i:]))
            if os.path.exists(alt):
                return alt
        return full


def _serve_dir(directory: str) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_FallbackHandler, directory=directory))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _shoot(browser: str, url: str, out: Path, size: tuple[int, int], timeout: int = 25):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.png")
    tmp.unlink(missing_ok=True)
    scale = 2 if size == PHONE else 1
    base = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
            "--disable-extensions", "--disable-sync", f"--user-data-dir={PROFILE}",
            f"--force-device-scale-factor={scale}", f"--window-size={size[0]},{size[1]}", f"--screenshot={tmp}"]
    # The virtual-time budget lets JS-rendered pages settle, but some pages never go idle under it
    # (seen with a 390px phone viewport), so retry once without it.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for extra in (["--virtual-time-budget=6000"], []):
        proc = subprocess.Popen(base + extra + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            proc.wait(timeout=timeout)
            break
        except subprocess.TimeoutExpired:
            # Kill the whole browser tree so no orphan keeps the profile locked.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, creationflags=flags)
    if not tmp.exists() or tmp.stat().st_size < 3000:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Browser produced no screenshot for {url}")
    tmp.replace(out)


def capture(key: str, *, preview_url: str | None, live_url: str | None, local_sources: list[str],
            phone: bool) -> dict:
    """Capture a preview for one project. Returns {"source": ..., "file": ...}."""
    browser = find_browser()
    if not browser:
        raise RuntimeError("No Edge or Chrome found for screenshots")
    out = preview_path(key)
    size = PHONE if phone else DESKTOP
    errors = []
    for url in (preview_url, live_url):
        if url:
            try:
                _shoot(browser, url, out, size)
                return {"source": url, "file": out.name}
            except Exception as e:  # try the next source
                errors.append(str(e))
    for src in local_sources:
        fp = Path(src)
        if not fp.is_file():
            continue
        httpd = _serve_dir(str(fp.parent))
        try:
            _shoot(browser, f"http://127.0.0.1:{httpd.server_address[1]}/{fp.name}", out, size)
        except Exception as e:
            errors.append(str(e))
        finally:
            httpd.shutdown()
        # Some apps behave differently when served (e.g. wait for an API that a static server lacks) and
        # render blank. A nearly-empty PNG is small, so also try file:// and keep the more detailed image.
        if not out.exists() or out.stat().st_size < BLANKISH:
            alt = out.with_name(out.stem + ".file.png")
            try:
                _shoot(browser, fp.as_uri(), alt, size)
                if not out.exists() or alt.stat().st_size > out.stat().st_size:
                    alt.replace(out)
            except Exception as e:
                errors.append(str(e))
            finally:
                alt.unlink(missing_ok=True)
        if out.exists():
            return {"source": str(fp), "file": out.name}
    raise RuntimeError(errors[-1] if errors else "No preview source (set a live or preview URL)")
