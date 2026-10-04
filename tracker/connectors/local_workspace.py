import fnmatch
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

MARKERS = {'.git', 'package.json', 'pyproject.toml', 'requirements.txt', 'Cargo.toml', 'Dockerfile', 'README.md', 'app.py', 'main.py'}
IGNORE = ['.git', '.env', '.env.*', '.ssh', '.aws', '.codex', '.claude', 'node_modules', 'venv', '.venv', 'dist', 'build', 'target', '__pycache__', '*cache*', 'AppData', 'Windows', 'Program Files*', '*browser*', '*.pem', '*.key', '*credentials*', '*token*', '*secret*']
LANG = {'.py':'Python', '.js':'JavaScript', '.ts':'TypeScript', '.tsx':'TypeScript', '.rs':'Rust', '.go':'Go', '.cs':'C#'}

def git(path, *args):
    try:
        r = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

def ignored(name, patterns):
    return any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns)

def discover(roots, extra_ignore=(), max_depth=5):
    patterns = IGNORE + list(extra_ignore)
    projects, warnings = [], []
    for root in roots:
        base = Path(root).resolve()
        if not base.is_dir():
            warnings.append('Configured workspace unavailable')
            continue
        for current, dirs, files in os.walk(base, followlinks=False):
            path = Path(current)
            dirs[:] = [d for d in dirs if not ignored(d, patterns) and not (path/d).is_symlink() and not (hasattr((path/d), 'is_junction') and (path/d).is_junction())]
            if len(path.relative_to(base).parts) >= max_depth:
                dirs[:] = []
            if MARKERS.intersection(files) or (path/'.git').exists():
                projects.append(inspect(path, patterns))
                dirs[:] = []  # one card per recognized workspace, not every nested package
    unique = {p['path'].lower(): p for p in projects}
    return list(unique.values()), warnings

def inspect(path, patterns):
    languages, last, count, todos = Counter(), 0, 0, 0
    for current, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not ignored(d, patterns) and not (Path(current)/d).is_symlink() and not (hasattr(Path(current)/d,'is_junction') and (Path(current)/d).is_junction())]
        for name in files:
            fp = Path(current)/name
            if ignored(name, patterns) or fp.is_symlink():
                continue
            try:
                stat = fp.stat()
                count += 1
                last = max(last, stat.st_mtime)
                if fp.suffix in LANG:
                    languages[LANG[fp.suffix]] += 1
                    if stat.st_size < 100000:
                        # Only a count leaves the machine; comments and code are not uploaded.
                        text = fp.read_text(encoding='utf-8', errors='replace')
                        todos += text.count('TODO') + text.count('FIXME')
            except OSError:
                continue
        if count >= 8000:
            break
    commits = []
    for line in (git(path, 'log', '-30', '--format=%H|%cI') or '').splitlines():
        sha, _, ts = line.partition('|')
        if ts:
            commits.append({'sha': sha, 'timestamp': ts})
    status = git(path, 'status', '--porcelain')
    return {'name':path.name, 'path':str(path), 'repository':git(path,'remote','get-url','origin'), 'branch':git(path,'branch','--show-current'), 'git_observed':status is not None, 'changed_files':len(status.splitlines()) if status is not None else None, 'commits':commits, 'last_activity':datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None, 'language':languages.most_common(1)[0][0] if languages else '', 'file_count':count, 'todo_count':todos}
