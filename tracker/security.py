"""Access control for phone (LAN) access: login code, sessions, brute-force throttle, TLS certificate.

The PC itself talks to a loopback-only listener that needs no login. The phone talks to a separate HTTPS
listener that requires a login code and then a session cookie. Nothing here uses third-party packages.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

DATA = Path(os.environ.get('TRACKER_DATA_DIR', str(Path(__file__).resolve().parent.parent / "data")))
ACCESS_FILE = DATA / "access.json"
TLS_DIR = DATA / "tls"

LAN_PORT = 8766
COOKIE = "pt_session"
SESSION_DAYS = 30
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L so it can be read off a screen and typed
CODE_LEN = 12                                         # 31^12 is about 2^59 possibilities
MAX_FAILS, LOCK_SECONDS = 5, 15 * 60                  # per client IP
GLOBAL_FAILS, GLOBAL_WINDOW, GLOBAL_LOCK = 25, 600, 600

_lock = threading.RLock()
_ip_fails: dict[str, list] = {}      # ip -> [count, locked_until]
_recent_fails: deque = deque()
_global_locked_until = 0.0


# ------------------------------------------------------------------ stored state

def _load() -> dict:
    try:
        d = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("enabled", False)
    d.setdefault("code", "")
    d.setdefault("sessions", {})       # sha256(session token) -> expiry timestamp
    return d


def _save(d: dict):
    DATA.mkdir(exist_ok=True)
    tmp = ACCESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, ACCESS_FILE)


def _fmt(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def get_state() -> dict:
    with _lock:
        d = _load()
        if not d["code"]:
            d["code"] = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
            _save(d)
        return d


def is_enabled() -> bool:
    return bool(get_state()["enabled"])


def set_enabled(on: bool):
    with _lock:
        d = get_state()
        d["enabled"] = bool(on)
        if not on:
            d["sessions"] = {}
        _save(d)


def display_code() -> str:
    return _fmt(get_state()["code"])


def regenerate_code() -> str:
    """New code; every phone is signed out."""
    with _lock:
        d = get_state()
        d["code"] = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        d["sessions"] = {}
        _save(d)
    _ip_fails.clear()
    return _fmt(d["code"])


def session_count() -> int:
    with _lock:
        d = get_state()
        now = time.time()
        return sum(1 for exp in d["sessions"].values() if exp > now)


def revoke_all():
    with _lock:
        d = get_state()
        d["sessions"] = {}
        _save(d)


# ------------------------------------------------------------------ sessions

def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        d = get_state()
        now = time.time()
        d["sessions"] = {k: v for k, v in d["sessions"].items() if v > now}   # drop expired
        d["sessions"][_h(token)] = now + SESSION_DAYS * 86400
        _save(d)
    return token


def valid_session(token: str | None) -> bool:
    if not token or len(token) > 200:
        return False
    with _lock:
        exp = get_state()["sessions"].get(_h(token))
    return bool(exp and exp > time.time())


def end_session(token: str | None):
    if not token:
        return
    with _lock:
        d = get_state()
        if d["sessions"].pop(_h(token), None) is not None:
            _save(d)


def cookie_from(header: str | None) -> str | None:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


# ------------------------------------------------------------------ login throttle

def throttle_wait(ip: str) -> int:
    """Seconds this client must wait before trying a code again (0 = go ahead)."""
    now = time.time()
    with _lock:
        wait = max(_global_locked_until - now, (_ip_fails.get(ip) or [0, 0])[1] - now)
    return int(wait) + 1 if wait > 0 else 0


def try_code(ip: str, candidate: str) -> bool:
    """Check a login code, recording failures. Callers must check throttle_wait first."""
    global _global_locked_until
    ok = hmac.compare_digest(_norm(candidate).encode(), get_state()["code"].encode())
    now = time.time()
    with _lock:
        if ok:
            _ip_fails.pop(ip, None)
            return True
        rec = _ip_fails.setdefault(ip, [0, 0.0])
        rec[0] += 1
        if rec[0] >= MAX_FAILS:
            rec[0], rec[1] = 0, now + LOCK_SECONDS
        _recent_fails.append(now)
        while _recent_fails and _recent_fails[0] < now - GLOBAL_WINDOW:
            _recent_fails.popleft()
        if len(_recent_fails) >= GLOBAL_FAILS:
            _global_locked_until = now + GLOBAL_LOCK
            _recent_fails.clear()
    time.sleep(0.5)     # slows guessing even before a lockout
    return False


def try_password(ip: str, candidate: str, expected: str) -> bool:
    """Check a deployment password with the same per-IP and global login throttles."""
    global _global_locked_until
    now = time.time()
    with _lock:
        wait = max(_global_locked_until - now, (_ip_fails.get(ip) or [0, 0])[1] - now)
        if wait > 0:
            return False
        ok = hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
        if ok:
            _ip_fails.pop(ip, None)
            return True
        rec = _ip_fails.setdefault(ip, [0, 0.0])
        rec[0] += 1
        if rec[0] >= MAX_FAILS:
            rec[0], rec[1] = 0, now + LOCK_SECONDS
        _recent_fails.append(now)
        while _recent_fails and _recent_fails[0] < now - GLOBAL_WINDOW:
            _recent_fails.popleft()
        if len(_recent_fails) >= GLOBAL_FAILS:
            _global_locked_until = now + GLOBAL_LOCK
            _recent_fails.clear()
    time.sleep(0.5)
    return False


# ------------------------------------------------------------------ network identity

def is_private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_private and not a.is_unspecified


def lan_ips() -> list[str]:
    """This PC's private IPv4 addresses, the one used for the default route first."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # no packet is sent; this just picks the outgoing interface
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for ip in found:
        if ip not in out and is_private(ip) and not ip.startswith(("127.", "169.254.")):
            out.append(ip)
    return out


def host_ok(host_header: str, remote: bool, port: int, expected_host: str | None = None) -> bool:
    """Reject requests addressed to any name we don't own (DNS-rebinding defence)."""
    host = (host_header or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        name, _, rest = host[1:].partition("]")
        p = rest.lstrip(":")
    elif host.count(":") == 1:
        name, _, p = host.partition(":")
    else:
        name, p = host, ""
    if expected_host:
        expected = expected_host.strip().lower().rstrip(".")
        return name.rstrip(".") == expected and p in ("", str(port))
    if p != str(port):
        return False
    if not remote:
        return name in ("127.0.0.1", "localhost")
    try:
        return is_private(name) and not ipaddress.ip_address(name).is_loopback
    except ValueError:
        me = socket.gethostname().lower()
        return name in (me, me + ".local")


# ------------------------------------------------------------------ TLS certificate

def _openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        for rel in (r"Git\usr\bin\openssl.exe", r"Git\mingw64\bin\openssl.exe"):
            p = Path(base) / rel
            if p.is_file():
                return str(p)
    return None


def openssl_available() -> bool:
    return _openssl() is not None


def _wanted_names() -> list[str]:
    return [f"IP:{ip}" for ip in lan_ips()] + [f"DNS:{socket.gethostname()}", f"DNS:{socket.gethostname()}.local"]


def ensure_cert() -> tuple[Path, Path]:
    """A self-signed certificate covering this PC's current LAN addresses; recreated when they change."""
    cert, key, meta = TLS_DIR / "cert.pem", TLS_DIR / "key.pem", TLS_DIR / "meta.json"
    names = _wanted_names()
    try:
        have = json.loads(meta.read_text())
    except (OSError, ValueError):
        have = {}
    if cert.is_file() and key.is_file() and have.get("names") == names and have.get("expires", 0) > time.time() + 30 * 86400:
        return cert, key
    exe = _openssl()
    if not exe:
        raise RuntimeError("OpenSSL was not found. Install Git for Windows (it includes OpenSSL) and try again.")
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    cnf = TLS_DIR / "openssl.cnf"
    cnf.write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=Project Tracker\n"
        "[v3]\nsubjectAltName=" + ",".join(names) + "\nbasicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature\nextendedKeyUsage=serverAuth\n", encoding="utf-8")
    cmd = [exe, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-days", "365",
           "-keyout", str(key), "-out", str(cert), "-config", str(cnf)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not cert.is_file():
        raise RuntimeError("Could not create the TLS certificate: " + (r.stderr or r.stdout).strip()[-200:])
    meta.write_text(json.dumps({"names": names, "expires": time.time() + 365 * 86400}))
    return cert, key


def fingerprint() -> str:
    try:
        der = ssl.PEM_cert_to_DER_cert((TLS_DIR / "cert.pem").read_text())
    except (OSError, ValueError):
        return ""
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def server_context() -> ssl.SSLContext:
    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert), str(key))
    return ctx
