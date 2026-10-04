"""Bounded, local-only folder suggestions. Nothing is uploaded until the user selects roots."""
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, unquote

def suggestions(home=None):
    home=Path(home or Path.home())
    found={}
    def add(path,source):
        try:
            path=Path(path).expanduser().resolve()
            if path.is_dir() and not path.is_symlink():
                found.setdefault(str(path).lower(),{'path':str(path),'source':source})
        except (OSError,ValueError): pass
    add(Path(__file__).resolve().parents[2],'Collector repository')
    for relative in ('Projects','source/repos','repos','GitHub','Development','dev','Documents/Projects','Documents/GitHub','Documents','Desktop'):
        add(home/relative,'Common development folder')
    for env_name in ('OneDrive','OneDriveConsumer'):
        root=os.environ.get(env_name)
        if root:
            for sub in ('Projects','Documents/Projects','Documents/GitHub','Desktop'):
                add(Path(root)/sub,'OneDrive development folder')
    # Read only the single recent-workspaces key, never VS Code secrets/settings.
    state=home/'AppData/Roaming/Code/User/globalStorage/state.vscdb'
    if state.is_file():
        connection=None
        try:
            connection=sqlite3.connect(state.as_uri()+'?mode=ro',uri=True,timeout=1)
            row=connection.execute("SELECT value FROM ItemTable WHERE key='history.recentlyOpenedPathsList'").fetchone()
            if row:
                for entry in json.loads(row[0]).get('entries',[])[:40]:
                    uri=entry.get('folderUri') or entry.get('workspace',{}).get('configPath')
                    if isinstance(uri,str) and uri.startswith('file:'):
                        parsed=urlsplit(uri)
                        if parsed.netloc: continue
                        path=unquote(parsed.path)
                        if len(path)>2 and path[0]=='/' and path[2]==':': path=path[1:]
                        target=Path(path)
                        add(target.parent if target.suffix=='.code-workspace' else target,'VS Code recent workspace')
        except (sqlite3.Error,ValueError,TypeError): pass
        finally:
            if connection: connection.close()
    # Metadata only, capped: do not traverse the drive or parse prompt histories.
    for source,root in [('Claude',home/'.claude/projects'),('Codex',home/'.codex/sessions')]:
        if not root.is_dir(): continue
        try:
            for i,fp in enumerate(root.rglob('*.jsonl')):
                if i>=20: break
                if fp.is_symlink(): continue
                with fp.open(encoding='utf-8',errors='replace') as stream:
                    for _ in range(20):
                        line=stream.readline(100000)
                        if not line: break
                        try:
                            row=json.loads(line)
                            if not isinstance(row,dict): continue
                            payload=row.get('payload',{}) if row.get('type')=='session_meta' else {}
                            cwd=row.get('cwd') or (payload.get('cwd') if isinstance(payload,dict) else None)
                            if isinstance(cwd,str):
                                add(cwd,source+' recorded workspace')
                                break
                        except ValueError: continue
        except OSError: pass
    return list(found.values())[:50]
