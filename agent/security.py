"""One exclusion and path-containment policy for every local adapter."""
import fnmatch
import re
from pathlib import Path

EXCLUSIONS = ('.git', '.env', '.env.*', '.ssh', '.aws', '.azure', '.gcp', '.codex',
    '.claude', '.copilot', 'AppData', 'Windows', 'Program Files*', 'node_modules',
    'venv', '.venv', 'dist', 'build', 'target', '*cache*', '*.pem', '*.key',
    '*credential*', '*token*', '*secret*', '*api*key*', '*password*', '*cookies*')

def excluded(path):
    return any(fnmatch.fnmatch(part.lower(), pattern.lower()) for part in Path(path).parts for pattern in EXCLUSIONS)

def links(path):
    path = Path(path).absolute()
    return any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents))

def workspace(path):
    original = Path(path).expanduser().absolute()
    if links(original): raise ValueError('Workspace links/junctions are not allowed')
    root = original.resolve()
    if not root.is_dir() or excluded(root.relative_to(root.anchor)):
        raise ValueError('Workspace unavailable or excluded by security policy')
    git_dir = root / '.git'
    if not git_dir.is_dir() or links(git_dir):
        raise ValueError('MVP requires a real repository with an in-workspace .git directory')
    return root

def safe_path(root, relative):
    path = Path(root) / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or excluded(relative) or links(path): return None
    return path if path.resolve().is_relative_to(Path(root).resolve()) else None

def text(value, limit=300):
    value = re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or ''))
    value = re.sub(r'(?i)(?:bearer\s+\S+|(?:token|password|api[_-]?key|secret)\s*[=:]\s*\S+|(?:gh[pousr]_|sk-)[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})', '[REDACTED]', value)
    return value[:limit]
