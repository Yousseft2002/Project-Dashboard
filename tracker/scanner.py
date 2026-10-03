"""Read-only scanner: finds project folders and maps AI-tool sessions to them.

Produces one snapshot dict per machine. Uses only the standard library so the
same file can be copied to another PC and run there (Phase 3).
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

SNAPSHOT_VERSION = 2
HOME = Path.home()
ACTIVITY_DAYS = 30

SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "env", "__pycache__", "dist", "build",
    ".next", "out", "android", "ios", "vendor", ".gradle", "Pods", "site-packages",
    ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "coverage", ".turbo",
    ".svelte-kit", ".cache", "target", ".claude", ".expo",
}
# Folders directly under a root that are never projects.
NOT_PROJECTS = {
    "appdata", "application data", "contacts", "cookies", "desktop", "documents",
    "downloads", "favorites", "links", "local settings", "music", "my documents",
    "nethood", "onedrive", "pictures", "printhood", "recent", "saved games",
    "searches", "sendto", "start menu", "templates", "videos", "npm-cache", "tools",
    "my music", "my pictures", "my videos", "codex", "tax man", "project-tracker",
}
MARKERS = (
    ".git", "package.json", "requirements.txt", "pyproject.toml", "CLAUDE.md",
    "AGENTS.md", "README.md", "Cargo.toml", "go.mod", "index.html", "TIMELINE.md",
)
CODE_EXT = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".sql": "SQL", ".kt": "Kotlin",
    ".swift": "Swift", ".java": "Java", ".go": "Go", ".rs": "Rust", ".cs": "C#",
    ".c": "C", ".cpp": "C++", ".h": "C", ".sh": "Shell", ".ps1": "PowerShell",
    ".vue": "Vue", ".svelte": "Svelte", ".dart": "Dart",
}
DOC_PATTERN = re.compile(
    r"(plan|todo|handoff|checklist|roadmap|claude|agents|timeline|readme|changelog|notes)",
    re.I,
)
MAX_FILES = 8000
PROMPT_KEEP = 6


# ---------------------------------------------------------------- helpers

def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _parse_ts(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return s / 1000 if s > 1e11 else float(s)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


CODEX_REVIEWER = "The following is the Codex agent history"


def _clean_prompt(text: str) -> str | None:
    """Return a human prompt, or None for injected context / tool noise."""
    if not text:
        return None
    t = text.strip()
    if not t or t.startswith(("<", "## Referenced", "Caveat:", "# AGENTS.md instructions", "# Files mentioned by the user")):
        return None
    if t.startswith("[Request interrupted"):
        return None
    t = re.sub(r"\s+", " ", t)
    return t[:300]


def _run_git(path: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True,
            timeout=20, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


# ---------------------------------------------------------------- folders

def default_roots() -> list[Path]:
    return [HOME / "Documents", HOME / "Desktop", HOME, HOME / "python"]


def discover_folders(roots: list[Path]) -> list[Path]:
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name.lower() in NOT_PROJECTS:
                continue
            if any((child / m).exists() for m in MARKERS) or _has_code(child):
                found.setdefault(_norm(child), child)
    return list(found.values())


def _has_code(path: Path) -> bool:
    try:
        return any(p.suffix in CODE_EXT for p in path.iterdir() if p.is_file())
    except OSError:
        return False


def git_info(path: Path) -> dict | None:
    if not (path / ".git").exists():
        return None
    info: dict = {"branch": (_run_git(path, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or None}
    remote = _run_git(path, "remote", "get-url", "origin")
    info["remote"] = remote.strip() if remote else None
    roots = _run_git(path, "log", "--max-parents=0", "--format=%ct") or ""
    first = [int(x) for x in roots.split() if x.isdigit()]
    info["first_commit"] = _iso(min(first)) if first else None
    count = _run_git(path, "rev-list", "--count", "HEAD")
    info["commit_count"] = int(count.strip()) if count and count.strip().isdigit() else 0
    log = _run_git(path, "log", "-n", "10", "--format=%ct%x09%h%x09%s") or ""
    info["recent_commits"] = [
        {"ts": _iso(int(ts)), "hash": h, "subject": s[:160]}
        for ts, h, s in (line.split("\t", 2) for line in log.splitlines() if line.count("\t") >= 2)
    ]
    since = _run_git(path, "log", f"--since={ACTIVITY_DAYS}.days", "--format=%ct") or ""
    info["commit_ts"] = [int(x) for x in since.split() if x.isdigit()]
    status = _run_git(path, "status", "--porcelain") or ""
    lines = [line for line in status.splitlines() if line.strip()]
    info["uncommitted"] = len(lines)
    info["untracked"] = sum(1 for line in lines if line.startswith("??"))
    ahead = _run_git(path, "rev-list", "--count", "@{u}..HEAD")
    info["unpushed"] = int(ahead.strip()) if ahead and ahead.strip().isdigit() else None
    return info


def file_stats(path: Path) -> dict:
    langs: Counter = Counter()
    loc: Counter = Counter()
    todos = 0
    files = 0
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(path):
        if "pyvenv.cfg" in filenames or "python.exe" in filenames:
            dirnames[:] = []  # an embedded Python install or venv, not project code
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            files += 1
            if files > MAX_FILES:
                break
            fp = os.path.join(dirpath, name)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            lang = CODE_EXT.get(os.path.splitext(name)[1].lower())
            if not lang or st.st_size > 1_000_000 or ".min." in name:
                continue
            try:
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            lines = text.count("\n") + 1
            if len(text) / lines > 400:
                continue  # minified / generated bundle
            langs[lang] += 1
            loc[lang] += lines
            todos += len(re.findall(r"\b(TODO|FIXME|HACK|XXX)\b", text))
        if files > MAX_FILES:
            break
    return {
        "files": min(files, MAX_FILES),
        "truncated": files > MAX_FILES,
        "languages": dict(langs.most_common(6)),
        "loc": dict(loc.most_common(6)),
        "loc_total": sum(loc.values()),
        "todos": todos,
        "last_modified": _iso(newest),
    }


def detect_stack(path: Path) -> list[str]:
    tags: list[str] = []
    pkg = path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for dep, tag in (
                ("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"),
                ("vite", "Vite"), ("@capacitor/core", "Capacitor"), ("expo", "Expo"),
                ("tailwindcss", "Tailwind"), ("prisma", "Prisma"), ("@supabase/supabase-js", "Supabase"),
                ("express", "Express"), ("electron", "Electron"), ("stripe", "Stripe"),
            ):
                if dep in deps:
                    tags.append(tag)
            tags.append("Node")
        except (OSError, ValueError):
            tags.append("Node")
    req = path / "requirements.txt"
    if req.exists():
        text = req.read_text(encoding="utf-8", errors="ignore").lower()
        for dep, tag in (("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"),
                         ("streamlit", "Streamlit"), ("anthropic", "Claude API"), ("openai", "OpenAI API"),
                         ("supabase", "Supabase"), ("pytest", "pytest")):
            if dep in text:
                tags.append(tag)
        tags.append("Python")
    elif (path / "pyproject.toml").exists():
        tags.append("Python")
    for fname, tag in (("Dockerfile", "Docker"), ("capacitor.config.json", "Capacitor"),
                       ("capacitor.config.ts", "Capacitor"), ("codemagic.yaml", "Codemagic CI"),
                       ("vercel.json", "Vercel"), ("netlify.toml", "Netlify"), ("supabase", "Supabase"),
                       ("shopify", "Shopify"), (".github", "GitHub Actions"), ("manifest.json", "PWA")):
        if (path / fname).exists():
            tags.append(tag)
    return list(dict.fromkeys(tags))


def doc_info(path: Path) -> tuple[list[dict], str | None]:
    docs = []
    readme_excerpt = None
    try:
        entries = list(path.iterdir())
    except OSError:
        return [], None
    for p in entries:
        if p.is_file() and p.suffix.lower() in (".md", ".txt") and DOC_PATTERN.search(p.stem):
            try:
                st = p.stat()
            except OSError:
                continue
            docs.append({"name": p.name, "modified": _iso(st.st_mtime), "size": st.st_size})
            if p.stem.lower() == "readme" and readme_excerpt is None:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    text = ""
                paras = [s.strip() for s in re.split(r"\n\s*\n", text) if s.strip()]
                body = [s for s in paras if not s.startswith("#")]
                readme_excerpt = (body[0] if body else (paras[0] if paras else ""))[:400] or None
    docs.sort(key=lambda d: d["modified"] or "", reverse=True)
    return docs, readme_excerpt


CHECK_RE = re.compile(r"^\s*[-*] \[( |x|X)\]\s+(.+?)\s*$")
IMAGE_RE = re.compile(r"(screenshot|screen|preview|shot|hero|banner|mockup|og-image|og_image|store)", re.I)
HTML_DIRS = ("", "public", "www", "web", "docs", "ui", "static", "site", "dist", "build", "app")


def checklists(path: Path, docs: list[dict]) -> list[dict]:
    """Markdown task-list items (- [ ] / - [x]) from the project's plan docs."""
    files = [path / d["name"] for d in docs if d["name"].lower().endswith(".md")]
    if (path / "docs").is_dir():
        files += sorted((path / "docs").glob("*.md"))[:20]
    items = []
    for fp in files:
        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            m = CHECK_RE.match(line)
            if m:
                text = re.sub(r"[*_`]+", "", m.group(2))[:200]
                items.append({"text": text, "done": m.group(1) != " ", "file": fp.name})
                if len(items) >= 200:
                    return items
    return items


def preview_sources(path: Path) -> list[str]:
    """Local HTML entry points that can be screenshotted, best first."""
    found: list[str] = []
    cap = path / "capacitor.config.json"
    if cap.exists():
        try:
            web = json.loads(cap.read_text(encoding="utf-8", errors="ignore")).get("webDir")
            if web and (path / web / "index.html").exists():
                found.append(str(path / web / "index.html"))
        except (OSError, ValueError):
            pass
    for d in HTML_DIRS:
        fp = path / d / "index.html" if d else path / "index.html"
        if fp.exists():
            found.append(str(fp))
    for sub in sorted(path.glob("*/web/index.html"))[:2]:
        found.append(str(sub))
    out = path / "out"
    if out.is_dir():
        htmls = sorted(out.glob("*.html"), key=lambda f: f.stat().st_mtime, reverse=True)
        found += [str(f) for f in htmls[:1]]
    return list(dict.fromkeys(found))[:4]


def repo_images(path: Path) -> list[str]:
    images = []
    for dirpath, dirnames, filenames in os.walk(path):
        depth = len(Path(dirpath).relative_to(path).parts)
        if depth >= 3 or "pyvenv.cfg" in filenames or "python.exe" in filenames:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in (".png", ".jpg", ".jpeg", ".webp") and IMAGE_RE.search(name):
                fp = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(fp) > 8000:
                        images.append(fp)
                except OSError:
                    pass
        if len(images) >= 6:
            break
    return images[:6]


DIGEST_FILES = ("package.json", "requirements.txt", "pyproject.toml", "capacitor.config.json", "app.json",
                "vercel.json", "netlify.toml", "Dockerfile", "codemagic.yaml")
SECRETISH = re.compile(r"(\.env|secret|credential|token|password|\.pem$|\.key$|auth\.json)", re.I)
DIGEST_FILE_CHARS = 6000
DIGEST_TOTAL_CHARS = 45000


def digest(path: Path, docs: list[dict]) -> dict:
    """Compact read-only summary (file tree + key docs) so a project on another PC can still be analyzed."""
    tree: list[str] = []
    for dirpath, dirnames, filenames in os.walk(path):
        if "pyvenv.cfg" in filenames or "python.exe" in filenames:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        rel = Path(dirpath).relative_to(path)
        for name in sorted(filenames):
            tree.append(str(rel / name) if str(rel) != "." else name)
            if len(tree) >= 400:
                break
        if len(tree) >= 400:
            break
    names = [d["name"] for d in docs] + [f for f in DIGEST_FILES if (path / f).exists()]
    files, total = {}, 0
    for name in dict.fromkeys(names):
        if SECRETISH.search(name):
            continue
        try:
            text = (path / name).read_text(encoding="utf-8", errors="ignore")[:DIGEST_FILE_CHARS]
        except OSError:
            continue
        if total + len(text) > DIGEST_TOTAL_CHARS:
            break
        files[name] = text
        total += len(text)
    return {"tree": tree, "files": files}


# ---------------------------------------------------------------- sessions

class SessionCache:
    """Caches parsed session files by (mtime, size) so rescans are fast."""

    def __init__(self, path: Path | None):
        self.path = path
        self.data: dict = {}
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.data = {}
        self.used: set[str] = set()

    def get(self, fp: Path, parser):
        try:
            st = fp.stat()
        except OSError:
            return None
        key = str(fp)
        sig = [st.st_mtime, st.st_size]
        self.used.add(key)
        hit = self.data.get(key)
        if hit and hit.get("sig") == sig:
            return hit["v"]
        try:
            value = parser(fp)
        except Exception:  # a corrupt session file should never break the scan
            value = None
        self.data[key] = {"sig": sig, "v": value}
        return value

    def save(self):
        if not self.path:
            return
        self.data = {k: v for k, v in self.data.items() if k in self.used}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data), encoding="utf-8")


def _session(tool, sid, cwd, title, prompt_ts, prompts, start, end, turns=None):
    return {
        "tool": tool, "id": sid, "cwd": cwd, "title": title,
        "start": start, "end": end,
        "turns": turns if turns is not None else len(prompt_ts),
        "prompt_ts": prompt_ts[-400:], "prompts": prompts[-PROMPT_KEEP:],
    }


def parse_claude(fp: Path):
    cwd = title = None
    prompt_ts, prompts, all_ts = [], [], []
    with open(fp, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            # Skip giant lines (base64 images) cheaply unless they are user turns.
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            if t == "custom-title":
                title = d.get("customTitle") or title
                continue
            if t not in ("user", "assistant"):
                continue
            cwd = cwd or d.get("cwd")
            ts = _parse_ts(d.get("timestamp"))
            if ts:
                all_ts.append(ts)
            if t != "user" or d.get("isSidechain") or d.get("isMeta"):
                continue
            content = (d.get("message") or {}).get("content")
            texts = []
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                    continue
                texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            for text in texts:
                p = _clean_prompt(text)
                if p:
                    prompts.append(p)
                    if ts:
                        prompt_ts.append(ts)
                    break
    if not all_ts:
        return None
    s = _session("claude", fp.stem, cwd, title or (prompts[0][:80] if prompts else None),
                 prompt_ts, prompts, min(all_ts), max(all_ts))
    s["store"] = fp.parent.name
    return s


def parse_codex(fp: Path, names: dict | None = None):
    cwd = sid = None
    prompt_ts, prompts, all_ts = [], [], []
    turns = 0
    with open(fp, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ts = _parse_ts(d.get("timestamp"))
            if ts:
                all_ts.append(ts)
            p = d.get("payload")
            if not isinstance(p, dict):
                continue
            if d.get("type") == "session_meta":
                cwd = p.get("cwd")
                sid = p.get("id") or p.get("session_id")
            elif d.get("type") == "event_msg" and p.get("type") == "task_started":
                turns += 1
            elif d.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                for c in p.get("content") or []:
                    if isinstance(c, dict) and c.get("text", "").lstrip().startswith(CODEX_REVIEWER):
                        return None  # Codex's internal approval-review session, not the owner's work
                    text = _clean_prompt(c.get("text", "")) if isinstance(c, dict) else None
                    if text:
                        prompts.append(text)
                        if ts:
                            prompt_ts.append(ts)
                        break
    if not all_ts:
        return None
    return _session("codex", sid or fp.stem, cwd, None, prompt_ts, prompts,
                    min(all_ts), max(all_ts), turns or len(prompts))


def parse_copilot(folder: Path):
    meta = {}
    ws = folder / "workspace.yaml"
    if ws.exists():
        for line in ws.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
    prompt_ts, prompts, all_ts = [], [], []
    ev = folder / "events.jsonl"
    if ev.exists():
        with open(ev, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"user.message"' not in line and '"session.start"' not in line and '"assistant.turn_end"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                data = d.get("data") or {}
                ts = _parse_ts(d.get("timestamp") or data.get("startTime"))
                if ts:
                    all_ts.append(ts)
                if d.get("type") == "user.message":
                    text = _clean_prompt(data.get("content", ""))
                    if text:
                        prompts.append(text)
                        if ts:
                            prompt_ts.append(ts)
    for k in ("created_at", "updated_at"):
        ts = _parse_ts(meta.get(k))
        if ts:
            all_ts.append(ts)
    if not all_ts:
        return None
    title = meta.get("name", "")
    title = title.replace("\\r\\n", " ").replace("\\n", " ").lstrip("# ").strip()[:80] or None
    return _session("copilot", meta.get("id") or folder.name, meta.get("cwd"), title,
                    prompt_ts, prompts, min(all_ts), max(all_ts))


def parse_vscode_chat(fp: Path, folder: str | None = None):
    text = fp.read_text(encoding="utf-8", errors="ignore")
    prompts, prompt_ts, all_ts = [], [], []
    for m in re.finditer(r'"message":\{"text":"((?:[^"\\]|\\.)*)"', text):
        try:
            p = _clean_prompt(json.loads('"' + m.group(1) + '"'))
        except ValueError:
            p = None
        if p:
            prompts.append(p)
    for m in re.finditer(r'"(?:creationDate|timestamp|lastMessageDate)":(\d{12,})', text):
        all_ts.append(int(m.group(1)) / 1000)
    if not prompts:
        return None  # empty chat panels are noise
    if all_ts:
        prompt_ts = [max(all_ts)] * len(prompts)
    else:
        all_ts = [fp.stat().st_mtime]
    return _session("vscode", fp.stem, folder, prompts[0][:80], prompt_ts, prompts,
                    min(all_ts), max(all_ts))


def collect_sessions(cache: SessionCache) -> list[dict]:
    sessions: list[dict] = []

    claude_root = HOME / ".claude" / "projects"
    if claude_root.is_dir():
        for fp in claude_root.glob("*/*.jsonl"):
            s = cache.get(fp, parse_claude)
            if s:
                sessions.append(s)

    codex_root = HOME / ".codex"
    names = {}
    idx = codex_root / "session_index.jsonl"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(line)
                names[d["id"]] = d.get("thread_name")
            except (ValueError, KeyError):
                pass
    if (codex_root / "sessions").is_dir():
        for fp in (codex_root / "sessions").rglob("*.jsonl"):
            s = cache.get(fp, parse_codex)
            if s:
                s = dict(s, title=names.get(s["id"]) or s["title"])
                sessions.append(s)

    cop_root = HOME / ".copilot" / "session-state"
    if cop_root.is_dir():
        for folder in cop_root.iterdir():
            ev = folder / "events.jsonl"
            if folder.is_dir() and ev.exists():
                s = cache.get(ev, lambda _fp, f=folder: parse_copilot(f))
                if s:
                    sessions.append(s)

    appdata = os.environ.get("APPDATA")
    ws_root = Path(appdata) / "Code" / "User" / "workspaceStorage" if appdata else None
    if ws_root and ws_root.is_dir():
        for ws in ws_root.iterdir():
            folder = None
            wj = ws / "workspace.json"
            if wj.exists():
                try:
                    uri = json.loads(wj.read_text(encoding="utf-8")).get("folder")
                    if uri and uri.startswith("file:///"):
                        folder = unquote(uri[8:]).replace("/", os.sep)
                except (OSError, ValueError):
                    pass
            for fp in (ws / "chatSessions").glob("*.json*") if (ws / "chatSessions").is_dir() else []:
                s = cache.get(fp, lambda f, d=folder: parse_vscode_chat(f, d))
                if s:
                    sessions.append(s)
    return sessions


# ---------------------------------------------------------------- mapping

GENERAL_KEY = "general"


def _codex_workspace(cwd: str) -> bool:
    n = _norm(cwd)
    return any(n.startswith(_norm(r) + os.sep) for r in (HOME / "Documents" / "Codex", HOME / ".codex"))


def _slug(path: str) -> str:
    return re.sub(r"[^a-z0-9]", "-", _norm(path).lower())


def _words(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def infer_project(s: dict, folders: dict[str, Path]) -> str | None:
    """Place a session whose cwd is generic: by its Claude transcript folder, else by name mentions."""
    store = (s.get("store") or "").lower()
    if store:
        for key, path in folders.items():
            if store == _slug(str(path)):
                return key
    haystack = " " + _words(" ".join([s.get("title") or ""] + (s.get("prompts") or [])[:3])) + " "
    hits: Counter = Counter()
    for key, path in folders.items():
        w = _words(path.name)
        if len(w) < 4 or w in ("python", "project", "app"):
            continue
        for v in {w, w.replace(" ", "")}:
            hits[key] += haystack.count(" " + v + " ")
    ranked = [kv for kv in hits.most_common(2) if kv[1]] + [(None, 0)]
    if ranked[0][0] and ranked[0][1] > ranked[1][1]:
        return ranked[0][0]
    return None


def _is_general(cwd: str) -> bool:
    n = _norm(cwd)
    generic = {_norm(HOME), _norm(HOME / "Desktop"), _norm(HOME / "Documents")}
    if n in generic:
        return True
    lowered = n.lower()
    return ("appdata" in lowered and "scratch" in lowered) or (os.sep + ".copilot" + os.sep) in lowered


def _worktree_parent(cwd: str) -> str:
    # <repo>\.claude\worktrees\<name>  ->  <repo>
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == ".claude" and i + 1 < len(parts) and parts[i + 1] == "worktrees":
            return str(Path(*parts[:i]))
    return cwd


def build_snapshot(roots: list[Path] | None = None, cache_path: Path | None = None,
                   machine: str | None = None, progress=None, include_digest: bool = False) -> dict:
    t0 = time.time()
    machine = machine or socket.gethostname()
    say = progress or (lambda msg: None)
    roots = roots or default_roots()

    say("Finding project folders")
    folders = {_norm(p): p for p in discover_folders(roots)}

    say("Reading AI sessions")
    cache = SessionCache(cache_path)
    sessions = collect_sessions(cache)
    cache.save()

    # Session cwds that are real folders but weren't discovered become projects too.
    buckets: dict[str, list[dict]] = defaultdict(list)
    codex_names: dict[str, str] = {}
    for s in sessions:
        cwd = s.get("cwd")
        if not cwd:
            buckets[GENERAL_KEY].append(s)
            continue
        cwd = _worktree_parent(cwd)
        if _is_general(cwd):
            guess = infer_project(s, folders)
            if guess:
                s["inferred"] = True
            buckets[guess or GENERAL_KEY].append(s)
            continue
        if _codex_workspace(cwd):
            name = s.get("title") or Path(cwd).name
            key = "codex:" + re.sub(r"\W+", "-", name.lower()).strip("-")
            codex_names[key] = name
            buckets[key].append(s)
            continue
        n = _norm(cwd)
        match = max((k for k in folders if n == k or n.startswith(k + os.sep)), key=len, default=None)
        if match is None and Path(cwd).is_dir():
            folders[n] = Path(cwd)
            match = n
        buckets[match or GENERAL_KEY].append(s)

    cutoff = time.time() - ACTIVITY_DAYS * 86400
    projects = []
    keys = list(folders) + [k for k in codex_names]
    for i, key in enumerate(keys):
        path = folders.get(key)
        name = path.name if path else codex_names[key]
        say(f"Scanning {name} ({i + 1}/{len(keys)})")
        proj_sessions = buckets.get(key, [])
        proj = {
            "key": key, "name": name, "path": str(path) if path else None,
            "kind": "folder" if path else "codex-thread",
        }
        if path:
            proj["git"] = git_info(path)
            proj["files"] = file_stats(path)
            proj["stack"] = detect_stack(path)
            proj["docs"], proj["readme"] = doc_info(path)
            proj["checklist"] = checklists(path, proj["docs"])
            proj["preview_sources"] = preview_sources(path)
            proj["images"] = repo_images(path)
            if include_digest:
                proj["digest"] = digest(path, proj["docs"])
            try:
                proj["folder_created"] = _iso(path.stat().st_ctime)
            except OSError:
                proj["folder_created"] = None
        else:
            proj["git"], proj["files"], proj["stack"], proj["docs"], proj["readme"] = None, None, [], [], None
            proj["checklist"], proj["preview_sources"], proj["images"], proj["folder_created"] = [], [], [], None
        proj.update(_session_summary(proj_sessions, cutoff))
        proj["activity"] = _activity(proj, proj_sessions, cutoff)
        stamps = [proj["files"] and proj["files"].get("last_modified"), proj.get("ai_last")]
        if proj["git"] and proj["git"]["recent_commits"]:
            stamps.append(proj["git"]["recent_commits"][0]["ts"])
        proj["last_activity"] = max([s for s in stamps if s], default=None)
        born = [proj["folder_created"], (proj["git"] or {}).get("first_commit"), proj.get("ai_first")]
        proj["created"] = min([b for b in born if b], default=None)
        if proj["git"]:
            proj["git"].pop("commit_ts", None)
        projects.append(proj)

    general = _session_summary(buckets.get(GENERAL_KEY, []), cutoff)
    projects.sort(key=lambda p: p["last_activity"] or "", reverse=True)
    return {
        "version": SNAPSHOT_VERSION, "machine": machine,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "scan_seconds": round(time.time() - t0, 1),
        "roots": [str(r) for r in roots],
        "projects": projects, "general": general,
        "totals": {"sessions": len(sessions), "by_tool": dict(Counter(s["tool"] for s in sessions))},
    }


def _session_summary(sessions: list[dict], cutoff: float) -> dict:
    by_tool: dict[str, dict] = {}
    for s in sessions:
        t = by_tool.setdefault(s["tool"], {"sessions": 0, "sessions_30d": 0, "turns": 0, "last": 0})
        t["sessions"] += 1
        t["turns"] += s.get("turns") or 0
        t["last"] = max(t["last"], s["end"] or 0)
        if (s["end"] or 0) >= cutoff:
            t["sessions_30d"] += 1
    for t in by_tool.values():
        t["last"] = _iso(t["last"])
    recent = sorted(sessions, key=lambda s: s["end"] or 0, reverse=True)
    return {
        "ai_tools": by_tool,
        "ai_last": _iso(max((s["end"] or 0 for s in sessions), default=0)),
        "ai_first": _iso(min((s["start"] or 0 for s in sessions if s["start"]), default=0)),
        "recent_sessions": [
            {"tool": s["tool"], "title": s["title"], "end": _iso(s["end"]), "turns": s["turns"],
             "last_prompt": (s["prompts"] or [None])[-1]}
            for s in recent[:8]
        ],
        "recent_prompts": [
            {"tool": s["tool"], "text": p}
            for s in recent[:4] for p in reversed(s["prompts"][-3:])
        ][:10],
    }


def _activity(proj: dict, sessions: list[dict], cutoff: float) -> dict:
    days: dict[str, dict] = {}
    today = datetime.now().date()
    for i in range(ACTIVITY_DAYS):
        days[(today - timedelta(days=ACTIVITY_DAYS - 1 - i)).isoformat()] = {}
    for ts in (proj.get("git") or {}).get("commit_ts", []):
        d = _day(ts)
        if d in days:
            days[d]["commits"] = days[d].get("commits", 0) + 1
    for s in sessions:
        for ts in s.get("prompt_ts") or []:
            if ts >= cutoff:
                d = _day(ts)
                if d in days:
                    days[d][s["tool"]] = days[d].get(s["tool"], 0) + 1
    return days


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(f"{socket.gethostname()}.json")
    snap = build_snapshot(progress=lambda m: print(m, flush=True), include_digest=True)
    out.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    print(f"Wrote {out} — {len(snap['projects'])} projects in {snap['scan_seconds']}s")
