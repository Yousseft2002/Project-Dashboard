import hashlib
import json
import subprocess
import os
from collections import Counter
from datetime import datetime, timezone
from tracker.central import repository
from ..security import safe_path, text, workspace

def run(root, *args):
    env={key:value for key,value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(['git', '--no-pager', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=NUL',
        '-c', 'core.pager=cat', '-c', 'protocol.allow=never', '-C', str(root), *args],
        capture_output=True, encoding='utf-8', errors='replace', timeout=20,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),env=env)
    if result.returncode: raise ValueError('Git metadata unavailable for approved repository')
    return result.stdout

def snapshot(path, device_id):
    root = workspace(path)
    from ..security import links
    if any(links(root/'.git'/name) for name in ('config','HEAD','refs')):
        raise ValueError('Linked Git metadata is not allowed')
    if any((root/'.git'/name).exists() for name in ('commondir','objects/info/alternates')):
        raise ValueError('External Git object stores are not supported')
    try: includes=run(root,'config','--no-includes','--local','--get-regexp',r'^include')
    except ValueError: includes=''
    if includes: raise ValueError('Git config includes are not supported by the metadata-only MVP')
    remote = repository(run(root, 'config', '--get', 'remote.origin.url').strip()) if _has_remote(root) else None
    project_id = hashlib.sha256((remote or device_id + ':' + str(root).lower()).encode()).hexdigest()
    commits = []
    try: history=run(root, 'log', '-100', '--format=%H%x09%cI%x09%s')
    except ValueError:
        # A newly initialized repository has useful status but no commits yet.
        try: run(root,'rev-parse','--verify','HEAD')
        except ValueError: history=''
        else: raise
    for line in history.splitlines():
        fields = line.split('\t', 2)
        if len(fields) == 3:
            commits.append({'sha':fields[0], 'timestamp':fields[1], 'message':text(fields[2])})
    status = run(root, 'status', '--porcelain=v1', '-z', '--untracked-files=normal').split('\0')
    changed, latest, index = Counter(), 0.0, 0
    while index < len(status):
        row = status[index]; index += 1
        if len(row) < 4: continue
        flags, name = row[:2], row[3:]
        if 'R' in flags or 'C' in flags: index += 1
        target = safe_path(root, name)
        if target is None: continue
        changed['deleted' if 'D' in flags else 'added' if 'A' in flags or '?' in flags else 'modified'] += 1
        try: latest = max(latest, target.stat().st_mtime)
        except OSError: pass
    languages = Counter()
    extensions = {'.py':'Python','.ts':'TypeScript','.tsx':'TypeScript','.js':'JavaScript','.rs':'Rust','.go':'Go','.cs':'C#'}
    files = [name for name in run(root, 'ls-files', '-z').split('\0') if name and safe_path(root, name) is not None]
    from pathlib import Path
    for name in files:
        if Path(name).suffix.lower() in extensions: languages[extensions[Path(name).suffix.lower()]] += 1
    ahead = behind = 0
    try:
        ahead, behind = map(int, run(root, 'rev-list', '--left-right', '--count', 'HEAD...@{upstream}').split())
    except ValueError: pass
    timestamps = [c['timestamp'] for c in commits[:1]]
    if latest: timestamps.append(datetime.fromtimestamp(latest, timezone.utc).isoformat())
    project = {'name':text(root.name,150), 'path':str(root), 'repository':'https://' + remote if remote else '',
        'branch':text(run(root,'branch','--show-current').strip(),150), 'git_observed':True,
        'commits':commits, 'changed_files':sum(changed.values()), 'file_count':len(files),
        'todo_count':0, 'last_activity':max(timestamps, default=None),
        'language':languages.most_common(1)[0][0] if languages else '',
        'added_files':changed['added'], 'modified_files':changed['modified'], 'deleted_files':changed['deleted'],
        'ahead':ahead, 'behind':behind, 'head_sha':commits[0]['sha'] if commits else None}
    events = []
    for commit in commits:
        body = {'device_id':device_id,'project_id':project_id,'source':'git','event_type':'commit',
                'timestamp':commit['timestamp'],'summary':commit['message'], 'metadata':{'sha':commit['sha']}}
        body['event_id'] = hashlib.sha256(json.dumps([device_id,project_id,'commit',commit['sha']],separators=(',',':')).encode()).hexdigest()
        events.append(body)
    return project_id, project, events

def _has_remote(root):
    try: run(root, 'config', '--get', 'remote.origin.url'); return True
    except ValueError: return False
