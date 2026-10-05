"""Request-driven cloud services shared by the ASGI and socket adapters."""
import hashlib
import json
import secrets
import time
from contextlib import contextmanager
from . import agent_api, security

AGENT_OPERATIONS={('POST','register'),('POST','heartbeat'),('POST','projects'),
                  ('POST','events/batch'),('GET','status')}

def agent_operation(store,method,endpoint,authorization,body,limiter=None):
    if (method,endpoint) not in AGENT_OPERATIONS: return 404,{'error':'Agent operation not supported'},{}
    device=store.authenticate(authorization[7:] if authorization.startswith('Bearer ') else '')
    if not device: return 401,{'error':'Invalid or revoked device credential'},{}
    if (limiter or agent_api.limited)(device): return 429,{'error':'Agent rate limit reached'},{'Retry-After':'60'}
    if not isinstance(body,dict) or body.get('device_id',device)!=device:
        return 400,{'error':'Device identity mismatch'},{}
    try: return 200,agent_api.dispatch(store,device,endpoint,body),{}
    except (ValueError,TypeError): return 400,{'error':'Invalid agent metadata; local queue must be retained'},{}

class CloudAuth:
    """Hashed sessions and rate counters survive cold starts in PostgreSQL."""
    def __init__(self,db):
        self.db=db
        with db.conn() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS cloud_sessions(token_hash TEXT PRIMARY KEY,expires_at DOUBLE PRECISION NOT NULL);
            CREATE TABLE IF NOT EXISTS cloud_rate_windows(key TEXT NOT NULL,bucket INTEGER NOT NULL,hits INTEGER NOT NULL,PRIMARY KEY(key,bucket));''')
    def limited(self,key,limit,seconds=60):
        bucket=int(time.time())//seconds
        with self.db.conn() as c:
            c.execute('DELETE FROM cloud_rate_windows WHERE bucket<? AND key=?',(bucket-2,key))
            row=c.execute('INSERT INTO cloud_rate_windows VALUES (?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET hits=cloud_rate_windows.hits+1 RETURNING hits',(key,bucket)).fetchone()
        return row['hits']>limit
    def session(self):
        token=secrets.token_urlsafe(32)
        with self.db.conn() as c:
            c.execute('DELETE FROM cloud_sessions WHERE expires_at<?',(time.time(),))
            c.execute('INSERT INTO cloud_sessions VALUES (?,?)',(security._h(token),time.time()+security.SESSION_DAYS*86400))
        return token
    def valid(self,token):
        if not token or len(token)>200: return False
        with self.db.conn() as c: row=c.execute('SELECT expires_at FROM cloud_sessions WHERE token_hash=?',(security._h(token),)).fetchone()
        return bool(row and row['expires_at']>time.time())
    def logout(self,token):
        if token:
            with self.db.conn() as c: c.execute('DELETE FROM cloud_sessions WHERE token_hash=?',(security._h(token),))

@contextmanager
def owner_context(db,store):
    # Existing route functions are services; no Handler instance or listener is used.
    from . import server
    previous={key:getattr(server._ctx,key,None) for key in ('database','central_store','cloud','remote')}
    server._ctx.database=db; server._ctx.central_store=store
    server._ctx.cloud=True; server._ctx.remote=False
    try: yield server
    finally:
        for key,value in previous.items(): setattr(server._ctx,key,value)

def owner_operation(db,store,method,path,body):
    from . import server
    if server.LOCAL_ONLY.match(path): return 403,{'error':'This can only be done on the PC itself.'}
    if (path.startswith('/api/scan') or path.startswith('/api/analyze') or path in ('/api/previews','/api/previews/upload','/api/planner/instruction','/api/cloud/push')):
        return 501,{'error':'This feature requires the local development server.'}
    if path=='/api/repo-image': return 404,{'error':'Local repository images are unavailable'}
    with owner_context(db,store):
        for verb,pattern,function in server.ROUTES:
            match=pattern.match(path)
            if verb==method and match: return 200,function(body,**match.groupdict())
    return 404,{'error':'not found'}
