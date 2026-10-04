"""Incremental metadata store. No source files or session prompt bodies accepted."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

SCHEMA = '''
CREATE TABLE IF NOT EXISTS central_projects(id TEXT PRIMARY KEY, identity TEXT UNIQUE NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, last_seen TEXT, revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS observations(project_id TEXT REFERENCES central_projects(id), device_id TEXT REFERENCES devices(id), data TEXT NOT NULL, synced_at TEXT NOT NULL, PRIMARY KEY(project_id,device_id));
CREATE TABLE IF NOT EXISTS sources(device_id TEXT, name TEXT, status TEXT, last_success TEXT, projects INTEGER DEFAULT 0, activities INTEGER DEFAULT 0, warnings TEXT DEFAULT '[]', errors TEXT DEFAULT '[]', PRIMARY KEY(device_id,name));
CREATE TABLE IF NOT EXISTS activities(id TEXT PRIMARY KEY, project_id TEXT REFERENCES central_projects(id), device_id TEXT, source TEXT, event_type TEXT, timestamp TEXT, summary TEXT, observed INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS activities_time ON activities(timestamp);
CREATE TABLE IF NOT EXISTS ai_sessions(id TEXT PRIMARY KEY, project_id TEXT REFERENCES central_projects(id), device_id TEXT, source TEXT, timestamp TEXT);
CREATE TABLE IF NOT EXISTS ingestion_events(id INTEGER PRIMARY KEY, device_id TEXT, timestamp TEXT, status TEXT, reason TEXT, projects INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sync_requests(device_id TEXT PRIMARY KEY, requested_at TEXT, fulfilled_at TEXT);
'''

def now():
    return datetime.now(timezone.utc).isoformat()

def repository(remote):
    """Canonicalize HTTPS/SSH without retaining credentials, query strings or fragments."""
    s = str(remote or '').strip()
    if not s:
        return None
    if re.match(r'^[\w.-]+@[\w.-]+:', s):
        s = 'ssh://' + s.replace(':', '/', 1)
    u = urlsplit(s)
    if u.scheme not in ('http', 'https', 'ssh', 'git') or not u.hostname:
        return None
    path = re.sub(r'\.git$', '', u.path.strip('/'))
    if not path or '..' in path.split('/'):
        return None
    return u.hostname.lower() + '/' + (path.lower() if u.hostname.lower() == 'github.com' else path)

def timestamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        if dt.timestamp() > datetime.now(timezone.utc).timestamp() + 300:
            raise ValueError()
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Invalid or future timestamp')

def clean_project(p):
    if not isinstance(p, dict):
        raise ValueError('Project must be an object')
    name, path = p.get('name'), p.get('path')
    if not isinstance(name, str) or not name.strip() or len(name) > 150:
        raise ValueError('Project name required (maximum 150 characters)')
    if not isinstance(path, str) or not path or len(path) > 1000:
        raise ValueError('Project path required')
    out = {'name': name.strip(), 'path': path, 'repository': repository(p.get('repository'))}
    out['git_observed'] = p.get('git_observed', bool(out['repository'] or p.get('commits')))
    if type(out['git_observed']) is not bool:
        raise ValueError('Invalid Git observation status')
    if p.get('project_id'):
        if not re.fullmatch(r'[\w.-]{1,100}', str(p['project_id'])):
            raise ValueError('Invalid explicit project ID')
        out['project_id'] = p['project_id']
    for field in ('branch', 'language', 'framework'):
        if p.get(field) is not None:
            if not isinstance(p[field], str):
                raise ValueError('Invalid metadata field')
            out[field] = p[field][:150]
    for field in ('changed_files', 'todo_count', 'file_count'):
        n = p.get(field, 0)
        if field == 'changed_files' and n is None:
            out[field] = None
            continue
        if type(n) is not int or not 0 <= n <= 10000000:
            raise ValueError('Invalid metadata count')
        out[field] = n
    out['last_activity'] = timestamp(p['last_activity']) if p.get('last_activity') else None
    commits = p.get('commits', [])
    if not isinstance(commits, list) or len(commits) > 100:
        raise ValueError('Maximum 100 commit metadata entries')
    out['commits'] = []
    for commit in commits:
        if not isinstance(commit, dict) or not re.fullmatch(r'[a-fA-F0-9]{7,64}', str(commit.get('sha', ''))):
            raise ValueError('Invalid commit SHA')
        out['commits'].append({'sha': commit['sha'].lower(), 'timestamp': timestamp(commit.get('timestamp'))})
    sessions = p.get('ai_sessions', [])
    if not isinstance(sessions,list) or len(sessions)>100:
        raise ValueError('Maximum 100 session metadata entries')
    out['ai_sessions'] = []
    for s in sessions:
        if not isinstance(s,dict) or s.get('source') not in ('claude','codex') or not re.fullmatch(r'[a-f0-9]{64}',str(s.get('session_id',''))):
            raise ValueError('Invalid session metadata')
        out['ai_sessions'].append({'source':s['source'],'session_id':s['session_id'],'timestamp':timestamp(s.get('timestamp'))})
    # Intentionally ignore unknown fields: no README, prompts, commands, patches, env or file contents.
    return out

class CentralStore:
    def __init__(self, db):
        self.db = db
        with db.conn() as c:
            c.executescript(SCHEMA)

    def register(self, device):
        if not isinstance(device, str) or not re.fullmatch(r'[\w.-]{1,80}', device):
            raise ValueError('Device ID must contain 1–80 letters, numbers, dots, dashes or underscores')
        token = secrets.token_urlsafe(32)
        with self.db.conn() as c:
            c.execute('INSERT INTO devices(id,token_hash) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash,revoked=0', (device, hashlib.sha256(token.encode()).hexdigest()))
        return {'device_id': device, 'token': token}

    def authenticate(self, token):
        if not token or len(token) > 200:
            return None
        with self.db.conn() as c:
            r = c.execute('SELECT id FROM devices WHERE token_hash=? AND revoked=0', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return r['id'] if r else None

    def log(self, device, status, reason, count=0):
        with self.db.conn() as c:
            c.execute('INSERT INTO ingestion_events(device_id,timestamp,status,reason,projects) VALUES (?,?,?,?,?)', (device, now(), status, reason, count))

    def heartbeat(self, device):
        with self.db.conn() as c:
            c.execute('UPDATE devices SET last_seen=? WHERE id=?', (now(), device))
            row = c.execute('SELECT requested_at,fulfilled_at FROM sync_requests WHERE device_id=?', (device,)).fetchone()
        return {'ok': True, 'sync_requested': bool(row and (not row['fulfilled_at'] or row['requested_at'] > row['fulfilled_at']))}

    def ingest(self, device, body):
        incoming = body.get('projects')
        if not isinstance(incoming, list) or len(incoming) > 500:
            raise ValueError('projects must be a list with at most 500 entries')
        projects = [clean_project(p) for p in incoming]  # validate whole batch before changing anything
        stamp = now()
        reports = body.get('sources', [])
        if not isinstance(reports, list) or len(reports) > 20:
            raise ValueError('Invalid source reports')
        for r in reports:
            if not isinstance(r, dict) or r.get('name') not in ('workspace', 'git', 'vscode', 'claude', 'codex', 'github', 'render') or r.get('status') not in ('connected', 'inferred', 'unavailable', 'error', 'not_configured'):
                raise ValueError('Invalid source status')
        with self.db.conn() as c:
            for p in projects:
                identity = 'repo:' + p['repository'] if p['repository'] else 'explicit:' + p['project_id'] if p.get('project_id') else 'local:' + device + ':' + p['path'].replace('\\', '/').lower()
                pid = 'project-' + hashlib.sha256(identity.encode()).hexdigest()[:24]
                # Preserve ID if a path acquires a remote later. Collapse into existing canonical repo if needed.
                old = c.execute('SELECT project_id,data FROM observations WHERE device_id=?', (device,)).fetchall()
                prior = next((r for r in old if json.loads(r['data'])['path'].replace('\\', '/').lower() == p['path'].replace('\\', '/').lower()), None)
                canonical = c.execute('SELECT id FROM central_projects WHERE identity=?', (identity,)).fetchone()
                if canonical:
                    pid = canonical['id']
                elif prior:
                    pid = prior['project_id']
                    c.execute('UPDATE central_projects SET identity=? WHERE id=?', (identity, pid))
                c.execute('INSERT INTO central_projects(id,identity,name) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name', (pid, identity, p['name']))
                if prior and prior['project_id'] != pid:
                    old_id = prior['project_id']
                    c.execute('UPDATE OR IGNORE observations SET project_id=? WHERE project_id=?', (pid, old_id))
                    c.execute('DELETE FROM observations WHERE project_id=?', (old_id,))
                    c.execute('UPDATE activities SET project_id=? WHERE project_id=?', (pid, old_id))
                    c.execute('UPDATE ai_sessions SET project_id=? WHERE project_id=?', (pid, old_id))
                    for table, column in (('items','project_key'), ('digital_overrides','key'), ('analyses','key'), ('directives','project_key'), ('plan_tasks','project_key')):
                        c.execute(f'UPDATE OR IGNORE {table} SET {column}=? WHERE {column}=?', (pid, old_id))
                    c.execute('DELETE FROM central_projects WHERE id=?', (old_id,))
                c.execute('INSERT INTO observations VALUES (?,?,?,?) ON CONFLICT(project_id,device_id) DO UPDATE SET data=excluded.data,synced_at=excluded.synced_at', (pid, device, json.dumps(p), stamp))
                for commit in p['commits']:
                    self._event(c, pid, device, 'git', 'commit', commit['timestamp'], 'Commit ' + commit['sha'][:12], 'commit:' + identity + ':' + commit['sha'])
                for session in p['ai_sessions']:
                    sid = session['source'] + ':' + session['session_id']
                    c.execute('INSERT INTO ai_sessions VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET timestamp=MAX(ai_sessions.timestamp,excluded.timestamp)', (sid,pid,device,session['source'],session['timestamp']))
                    self._event(c,pid,device,session['source'],'ai_session',session['timestamp'],'Local session metadata observed (prompt and outcome unavailable)',sid)
                    c.execute('UPDATE activities SET timestamp=MAX(timestamp,?) WHERE id=?', (session['timestamp'],hashlib.sha256(sid.encode()).hexdigest()))
                if p['last_activity']:
                    self._event(c, pid, device, 'workspace', 'file_change', p['last_activity'], 'Workspace modification observed; editor activity inferred', 'files:' + pid + ':' + device + ':' + p['last_activity'])
            for r in reports:
                ok = r['status'] in ('connected', 'inferred')
                c.execute('INSERT INTO sources(device_id,name,status,last_success,projects,activities,warnings,errors) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(device_id,name) DO UPDATE SET status=excluded.status,last_success=COALESCE(excluded.last_success,sources.last_success),projects=excluded.projects,warnings=excluded.warnings,errors=excluded.errors', (device, r['name'], r['status'], stamp if ok else None, len(projects) if ok else 0, 0, json.dumps(['Derived from filesystem metadata'] if r['status']=='inferred' else []), json.dumps(['Connector unavailable; check collector console'] if r['status']=='error' else [])))
            c.execute('UPDATE devices SET last_seen=? WHERE id=?', (stamp, device))
            c.execute('UPDATE sync_requests SET fulfilled_at=? WHERE device_id=?', (stamp, device))
            c.execute('INSERT INTO ingestion_events(device_id,timestamp,status,reason,projects) VALUES (?,?,?,?,?)', (device, stamp, 'accepted', 'Metadata merged', len(projects)))
        return {'ok': True, 'projects': len(projects), 'last_synced': stamp}

    def _event(self, c, pid, device, source, kind, ts, summary, identity):
        eid = hashlib.sha256(identity.encode()).hexdigest()
        c.execute('INSERT OR IGNORE INTO activities VALUES (?,?,?,?,?,?,?,?)', (eid, pid, device, source, kind, ts, summary, 1))

    def snapshot(self):
        with self.db.conn() as c:
            devices = [dict(r) for r in c.execute('SELECT id,last_seen,revoked FROM devices')]
            sources = [dict(r) for r in c.execute('SELECT * FROM sources')]
            events = [dict(r) for r in c.execute('SELECT * FROM activities ORDER BY timestamp DESC LIMIT 500')]
            rows = [dict(r) for r in c.execute('SELECT * FROM central_projects')]
            observations = [dict(r) for r in c.execute('SELECT * FROM observations ORDER BY synced_at DESC')]
            logs = [dict(r) for r in c.execute('SELECT * FROM ingestion_events ORDER BY id DESC LIMIT 50')]
            requests = [dict(r) for r in c.execute('SELECT * FROM sync_requests')]
            sessions = [dict(r) for r in c.execute('SELECT * FROM ai_sessions ORDER BY timestamp DESC')]
        for d in devices:
            d['status'] = 'revoked' if d['revoked'] else 'online' if d['last_seen'] and (datetime.now(timezone.utc)-datetime.fromisoformat(d['last_seen'])).total_seconds() < 180 else 'offline'
        for s in sources:
            s['warnings'], s['errors'] = json.loads(s['warnings']), json.loads(s['errors'])
            if next((d['status'] for d in devices if d['id']==s['device_id']), 'offline') != 'online':
                s['status'] = 'offline'
        for p in rows:
            p['observations'] = [dict(json.loads(o['data']), device_id=o['device_id'], synced_at=o['synced_at']) for o in observations if o['project_id']==p['id']]
            p['timeline'] = [e for e in events if e['project_id']==p['id']]
            p['ai_sessions'] = [s for s in sessions if s['project_id']==p['id']]
        return {'projects': rows, 'devices': devices, 'sources': sources, 'activity': events, 'ingestion': logs, 'sync_requests': requests}

    def raw_projects(self):
        out = []
        for p in self.snapshot()['projects']:
            obs = p['observations']
            if not obs:
                continue
            latest = obs[0]
            commits = {x['sha']: x for o in obs for x in o['commits']}
            recent = sorted(commits.values(), key=lambda x:x['timestamp'], reverse=True)
            out.append({'key': p['id'], 'name': p['name'], 'path': latest['path'], 'machine': latest['device_id'], 'machines': [o['device_id'] for o in obs], 'kind': 'folder', 'git': {'remote': 'https://' + latest['repository'] if latest['repository'] else None, 'branch': latest.get('branch'), 'uncommitted': latest['changed_files'], 'recent_commits': [{'hash': x['sha'], 'ts': x['timestamp'], 'subject': 'Commit '+x['sha'][:12]} for x in recent], 'commit_count': len(recent)}, 'files': {'last_modified': latest['last_activity'], 'files': latest['file_count'], 'todos': latest['todo_count']}, 'stack': [v for v in (latest.get('language'), latest.get('framework')) if v], 'activity': {}, 'ai_tools': {}, 'recent_sessions': [], 'recent_prompts': [], 'last_activity': max((o['last_activity'] for o in obs if o['last_activity']), default=None), 'central': p, 'last_synced': latest['synced_at'], 'todo_count': latest['todo_count']})
            raw = out[-1]
            if not latest['git_observed']:
                raw['git'] = None
            for session in p['ai_sessions']:
                tool = raw['ai_tools'].setdefault(session['source'], {'sessions':0,'sessions_30d':0,'turns':0,'last':None})
                tool['sessions'] += 1
                if (datetime.now(timezone.utc)-datetime.fromisoformat(session['timestamp'])).days < 30:
                    tool['sessions_30d'] += 1
                tool['last'] = max(tool['last'] or '',session['timestamp'])
            raw['ai_last'] = max((s['timestamp'] for s in p['ai_sessions']),default=None)
            raw['last_activity'] = max(filter(None,[raw['last_activity'],raw['ai_last']]),default=None)
            raw['recent_sessions'] = [{'tool':s['source'],'title':'Session metadata only','end':s['timestamp'],'turns':None,'last_prompt':None} for s in p['ai_sessions'][:8]]
        return out
