import hashlib
import json
import sqlite3
from contextlib import closing
from .storage import encode, decode

class Queue:
    def __init__(self, path):
        self.path = str(path)
        with closing(self.connect()) as c, c:
            c.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,data TEXT NOT NULL,fingerprint TEXT NOT NULL,server_id TEXT,dirty INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY);
            ''')
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20); c.row_factory=sqlite3.Row; return c
    def put(self, pid, project, events):
        data=json.dumps(project,sort_keys=True); fingerprint=hashlib.sha256(data.encode()).hexdigest()
        with closing(self.connect()) as c, c:
            c.execute('INSERT INTO projects VALUES (?,?,?,NULL,1) ON CONFLICT(id) DO UPDATE SET data=excluded.data,dirty=CASE WHEN projects.fingerprint!=excluded.fingerprint THEN 1 ELSE projects.dirty END,fingerprint=excluded.fingerprint',(pid,encode(data),fingerprint))
            for event in events:
                if c.execute('SELECT 1 FROM seen WHERE id=?',(event['event_id'],)).fetchone(): continue
                if c.execute('SELECT COUNT(*) FROM events').fetchone()[0]>=100000:
                    raise ValueError('Offline queue capacity reached; no queued events were discarded')
                c.execute('INSERT OR IGNORE INTO events VALUES (?,?,?)',(event['event_id'],pid,encode(json.dumps(event))))
    def projects(self, force=False):
        with closing(self.connect()) as c:
            return [dict(row,data=decode(row['data'])) for row in c.execute('SELECT * FROM projects' + ('' if force else ' WHERE dirty=1'))]
    def mapped(self, rows, ids):
        with closing(self.connect()) as c, c:
            for row, server_id in zip(rows,ids):
                c.execute('UPDATE projects SET server_id=?,dirty=CASE WHEN fingerprint=? THEN 0 ELSE dirty END WHERE id=?',(server_id,row['fingerprint'],row['id']))
    def events(self, limit=100):
        with closing(self.connect()) as c:
            rows=c.execute('SELECT events.data,projects.server_id FROM events JOIN projects ON projects.id=events.project_id WHERE projects.server_id IS NOT NULL ORDER BY events.rowid LIMIT ?',(limit,)).fetchall()
            return [dict(json.loads(decode(row['data'])),project_id=row['server_id']) for row in rows]
    def acknowledge(self, ids):
        with closing(self.connect()) as c, c:
            for event_id in ids:
                c.execute('INSERT OR IGNORE INTO seen VALUES (?)',(event_id,))
                c.execute('DELETE FROM events WHERE id=?',(event_id,))
    def pending(self):
        with closing(self.connect()) as c:
            return c.execute('SELECT COUNT(*) FROM events').fetchone()[0]
