"""Best-effort local JSONL metadata adapters; prompt/tool bodies never leave the device."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

def normalize(path):
    return os.path.normcase(os.path.normpath(str(path))).replace('\\','/').lower().rstrip('/')

def collect_sessions(projects, roots=None):
    roots = roots or {}
    reports = []
    home = Path.home()
    for source, fallback in [('claude',home/'.claude'/'projects'),('codex',home/'.codex'/'sessions')]:
        root = Path(roots.get(source, str(fallback))).expanduser()
        if not root.is_dir():
            reports.append({'name':source,'status':'unavailable'})
            continue
        errors = False
        try:
            files = list(root.rglob('*.jsonl'))[:500]
            for fp in files:
                if fp.is_symlink() or fp.stat().st_size > 20_000_000:
                    continue
                cwd, sid, latest = None, None, None
                with fp.open(encoding='utf-8',errors='replace') as stream:
                    for line in stream:
                        if len(line) > 1_000_000:
                            continue
                        try:
                            row = json.loads(line)
                            if not isinstance(row,dict):
                                continue
                            payload = row.get('payload') if row.get('type')=='session_meta' else {}
                            payload = payload if isinstance(payload,dict) else {}
                            cwd = row.get('cwd') or payload.get('cwd') or cwd
                            sid = row.get('sessionId') or payload.get('id') or payload.get('session_id') or sid
                            ts = row.get('timestamp')
                            if ts:
                                dt = datetime.fromisoformat(str(ts).replace('Z','+00:00'))
                                if dt.tzinfo and dt <= datetime.now(timezone.utc):
                                    latest = max(latest,dt) if latest else dt
                        except (ValueError,TypeError):
                            continue
                if not isinstance(cwd,str) or not latest:
                    continue
                matches = [p for p in projects if normalize(cwd)==normalize(p['path']) or normalize(cwd).startswith(normalize(p['path'])+'/')]
                if matches:
                    project = max(matches,key=lambda p:len(p['path']))
                    project.setdefault('ai_sessions',[]).append({'source':source, 'session_id':hashlib.sha256((source+':'+str(sid or fp.stem)).encode()).hexdigest(), 'timestamp':latest.astimezone(timezone.utc).isoformat()})
        except OSError:
            errors = True
        reports.append({'name':source,'status':'error' if errors else 'connected'})
    for p in projects:
        p['ai_sessions'] = sorted(p.get('ai_sessions',[]),key=lambda s:s['timestamp'],reverse=True)[:100]
    return reports
