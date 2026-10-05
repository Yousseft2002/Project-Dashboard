"""Versioned metadata API. No remote execution or file access operations."""
import hashlib
import json
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from .central import timestamp
from agent.security import text

_lock=threading.Lock()
_requests=defaultdict(deque)

def limited(device):
    with _lock:
        now=time.monotonic(); window=_requests[device]
        while window and window[0]<now-60: window.popleft()
        if len(window)>=60: return True
        window.append(now); return False

def initialize(db):
    with db.conn() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS agent_events(
          event_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, project_id TEXT NOT NULL,
          source TEXT NOT NULL, event_type TEXT NOT NULL, timestamp TEXT NOT NULL,
          summary TEXT NOT NULL, metadata TEXT NOT NULL, UNIQUE(project_id,event_type,metadata));''')
        columns={row['name'] for row in c.execute('PRAGMA table_info(devices)')}
        for key,sql in {'agent_id':'TEXT','agent_version':'TEXT','queue_size':'INTEGER DEFAULT 0'}.items():
            if key not in columns: c.execute('ALTER TABLE devices ADD COLUMN '+key+' '+sql)

def event_batch(store,device,body):
    events=body.get('events')
    if not isinstance(events,list) or len(events)>100: raise ValueError('Batch must contain at most 100 events')
    validated=[]
    for event in events:
        if not isinstance(event,dict) or set(event)-{'event_id','device_id','project_id','source','event_type','timestamp','summary','metadata'}:
            raise ValueError('Invalid event schema')
        if event.get('device_id')!=device: raise ValueError('Event device mismatch')
        if not isinstance(event.get('event_id'),str) or not re.fullmatch('[a-f0-9]{64}',event['event_id']): raise ValueError('Invalid event ID')
        if not isinstance(event.get('project_id'),str) or not re.fullmatch(r'[\w.-]{1,100}',event['project_id']): raise ValueError('Invalid project ID')
        if event.get('source')!='git' or event.get('event_type')!='commit': raise ValueError('Only Git commit events supported in MVP')
        metadata=event.get('metadata')
        if not isinstance(metadata,dict) or set(metadata)!={'sha'} or not isinstance(metadata['sha'],str) or not re.fullmatch('[a-f0-9]{40,64}',metadata['sha']): raise ValueError('Invalid commit metadata')
        if not isinstance(event.get('summary'),str) or len(event['summary'])>300: raise ValueError('Invalid event summary')
        validated.append(dict(event,timestamp=timestamp(event.get('timestamp')),summary=text(event['summary'])))
    initialize(store.db)
    accepted=duplicates=0; acknowledged=[]
    with store.db.conn() as c:
        for event in validated:
            observed=c.execute('SELECT 1 FROM observations WHERE project_id=? AND device_id=?',(event['project_id'],device)).fetchone()
            if not observed: raise ValueError('Project is not registered to this device')
            existing=c.execute('SELECT device_id,project_id,metadata FROM agent_events WHERE event_id=?',(event['event_id'],)).fetchone()
            metadata=json.dumps(event['metadata'],sort_keys=True)
            if existing and (existing['device_id']!=device or existing['project_id']!=event['project_id'] or existing['metadata']!=metadata): raise ValueError('Event identity collision')
            inserted=c.execute('INSERT OR IGNORE INTO agent_events VALUES (?,?,?,?,?,?,?,?)',(event['event_id'],device,event['project_id'],'git','commit',event['timestamp'],event['summary'],metadata)).rowcount
            accepted+=inserted; duplicates+=1-inserted; acknowledged.append(event['event_id'])
            project=c.execute('SELECT identity FROM central_projects WHERE id=?',(event['project_id'],)).fetchone()
            identity='commit:'+project['identity']+':'+event['metadata']['sha']
            store._event(c,event['project_id'],device,'git','commit',event['timestamp'],event['summary'],identity)
            c.execute('UPDATE activities SET summary=? WHERE id=?',(event['summary'],hashlib.sha256(identity.encode()).hexdigest()))
    return {'ok':True,'device_id':device,'accepted':accepted,'duplicates':duplicates,'rejected':0,'errors':[], 'acknowledged':acknowledged,'database_write':True}

def dispatch(store,device,endpoint,body):
    initialize(store.db)
    if endpoint=='register':
        agent_id=str(uuid.UUID(str(body.get('agent_id'))))
        with store.db.conn() as c:
            old=c.execute('SELECT agent_id FROM devices WHERE id=?',(device,)).fetchone()
            if old['agent_id'] and old['agent_id']!=agent_id: raise ValueError('Agent identity changed; re-pair explicitly')
        result=store.register_collector(device,body)
        with store.db.conn() as c:
            c.execute('UPDATE devices SET agent_id=?,agent_version=? WHERE id=?',(agent_id,text(body.get('collector_version'),30),device))
        return result
    if endpoint=='heartbeat':
        count=body.get('queue_size',0)
        if type(count) is not int or not 0<=count<=100000: raise ValueError('Invalid queue size')
        result=store.heartbeat(device)
        with store.db.conn() as c: c.execute('UPDATE devices SET queue_size=?,agent_version=? WHERE id=?',(count,text(body.get('agent_version'),30),device))
        return result
    if endpoint=='projects': return store.ingest(device,body)
    if endpoint=='events/batch': return event_batch(store,device,body)
    if endpoint=='status': return store.collector_status(device)
    raise ValueError('Unsupported operation')
