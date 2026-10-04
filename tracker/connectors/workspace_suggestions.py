"""Local directory suggestions; never read AI session stores or project contents."""
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, unquote

BLOCKED = {'.copilot', '.codex', '.claude', 'appdata', 'node_modules', '.git', '.venv', 'venv', '__pycache__', 'globalstorage', 'workspaceStorage'.lower()}
COMMON = ('Projects', 'source/repos', 'repos', 'GitHub', 'Development', 'dev', 'Documents/Projects', 'Documents/GitHub', 'Documents', 'Desktop')

def suggestions(home=None):
    home = Path(home or Path.home()).resolve()
    found = {}
    def blocked(path):
        parts = path.relative_to(home).parts if path.is_relative_to(home) else path.parts
        return any(part.lower() in BLOCKED for part in parts)
    def add(path, source):
        try:
            original = Path(path).expanduser()
            if original.is_symlink(): return
            path = original.resolve()
            if path == home or not path.is_dir() or blocked(path): return
            key = str(path).lower()
            if (path / '.git').exists(): source = 'Detected Git repository'
            if key not in found or source == 'Detected Git repository':
                found[key] = {'path': str(path), 'source': source}
        except (OSError, ValueError): pass
    add(Path(__file__).resolve().parents[2], 'Collector repository')
    roots = [home / relative for relative in COMMON]
    for env_name in ('OneDrive', 'OneDriveConsumer'):
        root = os.environ.get(env_name)
        if root:
            roots.extend(Path(root) / sub for sub in ('Projects', 'Documents/Projects', 'Documents/GitHub', 'Desktop'))
    for root in roots: add(root, 'Common development folder')
    # Bounded directory-name discovery. Do not enter repositories or session stores.
    queue = [(root, 0) for root in roots if root.is_dir()]
    visited = set()
    while queue and len(visited) < 300:
        folder, depth = queue.pop(0)
        try:
            key = str(folder.resolve()).lower()
            if key in visited or folder.is_symlink() or blocked(folder.resolve()): continue
            visited.add(key)
            if (folder / '.git').exists():
                add(folder, 'Detected Git repository')
                continue
            if folder not in roots and any((folder / name).is_file() for name in ('package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod', 'pom.xml', 'CMakeLists.txt')):
                add(folder, 'Detected development project')
                continue
            if depth < 2:
                queue.extend((child, depth + 1) for child in sorted(folder.iterdir())[:100] if child.is_dir() and not child.name.startswith('.'))
        except (OSError, ValueError): pass
    state = home / 'AppData/Roaming/Code/User/globalStorage/state.vscdb'
    if state.is_file():
        connection = None
        try:
            connection = sqlite3.connect(state.as_uri() + '?mode=ro', uri=True, timeout=1)
            row = connection.execute("SELECT value FROM ItemTable WHERE key='history.recentlyOpenedPathsList'").fetchone()
            if row:
                for entry in json.loads(row[0]).get('entries', [])[:40]:
                    uri = entry.get('folderUri') or entry.get('workspace', {}).get('configPath')
                    if isinstance(uri, str) and uri.startswith('file:'):
                        parsed = urlsplit(uri)
                        if parsed.netloc: continue
                        path = unquote(parsed.path)
                        if len(path) > 2 and path[0] == '/' and path[2] == ':': path = path[1:]
                        target = Path(path)
                        add(target.parent if target.suffix == '.code-workspace' else target, 'VS Code recent workspace')
        except (sqlite3.Error, ValueError, TypeError): pass
        finally:
            if connection: connection.close()
    # Keep specific projects plus broad selection alternatives. Remove redundant
    # container parents when a more useful development container is available,
    # and remove recent subfolders inside an already suggested project.
    items = list(found.values())
    projects = [Path(item['path']) for item in items if item['source'] in ('Detected Git repository', 'Detected development project')]
    containers = [Path(item['path']) for item in items if item['source'] == 'Common development folder' and Path(item['path']).name not in ('Documents', 'Desktop')]
    def redundant(item):
        path = Path(item['path'])
        if item['source'] == 'Common development folder':
            return any(other != path and other.is_relative_to(path) for other in containers)
        return any(path != project and path.is_relative_to(project) for project in projects)
    return sorted((item for item in items if not redundant(item)), key=lambda item: (0 if item['source'] == 'Detected Git repository' else 1 if item['source'] == 'Detected development project' else 2, item['path'].lower()))[:50]
