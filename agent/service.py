"""Background service. The server can request reconciliation, never execution."""
import json
import signal
import threading
import time
from pathlib import Path
from collector import CollectorError, utc_now
from .auth import credential
from .api.client import AgentClient
from .config import load
from .identity import identity
from .queue import Queue
from .diagnostics import Diagnostics
from .adapters.git import snapshot
from .sync import flush

class InstanceLock:
    def __init__(self,path): self.path=path; self.file=None
    def __enter__(self):
        self.file=open(self.path,'a+b'); self.file.seek(0); self.file.write(b'0'); self.file.flush(); self.file.seek(0)
        try:
            if __import__('os').name=='nt':
                import msvcrt; msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl; fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); raise ValueError('Project Dashboard Agent is already running')
        return self
    def __exit__(self,*args): self.file.close()

def collect(config, queue):
    for path in config['workspaces']:
        pid,project,events=snapshot(path,config['device_id'])
        queue.put(pid,project,events)

def run(path, once=False, preview=False, local_development=False):
    config,path=load(path,local_development)
    if preview:
        output=[]
        for root in config['workspaces']:
            pid,project,events=snapshot(root,config['device_id'])
            output.append({'project_id':pid,'project':project,'events':events})
        print(json.dumps(output,indent=2)); return
    identity(config,path)
    runtime=path.parent/'data'/'agent'; runtime.mkdir(parents=True,exist_ok=True)
    with InstanceLock(runtime/'service.lock'):
        queue=Queue(runtime/'queue.sqlite'); diagnostics=Diagnostics(runtime/'diagnostics.json')
        queue.allowlist(config['workspaces'])
        queue.rebind(config['device_id'])
        token=credential(config,path)
        client=AgentClient(config['server'],token)
        stop=threading.Event(); requested=threading.Event()
        for signum in (signal.SIGINT,signal.SIGTERM): signal.signal(signum,lambda *_:stop.set())
        def collect_loop():
            while not stop.is_set():
                try:
                    collect(config,queue)
                    diagnostics.update(projects=len(queue.projects(True)),pending=queue.pending(),last_collection=utc_now())
                except Exception as error: diagnostics.error(error)
                stop.wait(30)
        collect(config,queue)
        if not once: threading.Thread(target=collect_loop,daemon=True).start()
        next_heartbeat=next_reconcile=0.0; retry=5; registered=False
        try:
            while not stop.is_set():
                try:
                    if not registered:
                        health=client.health()
                        if health.get('agent_api_version')!=1: raise CollectorError('Deploy agent API v1 before starting this agent')
                        client.register_agent(config); registered=True
                    now=time.monotonic()
                    if now>=next_heartbeat:
                        heartbeat=client.heartbeat_agent(config,queue.pending())
                        if heartbeat.get('sync_requested') is True: requested.set()
                        next_heartbeat=now+120
                    force=now>=next_reconcile or requested.is_set()
                    uploaded=flush(client,config,queue,force)
                    if force: next_reconcile=time.monotonic()+config['reconcile_seconds']; requested.clear()
                    diagnostics.update(connected=True,pending=queue.pending(),last_error=None,
                        server=config['server'],device=config['device_name'],agent_id=config['agent_id'])
                    if uploaded: diagnostics.update(last_sync=utc_now())
                    retry=5
                    if once: break
                    stop.wait(15)
                except Exception as error:
                    diagnostics.error(error); diagnostics.update(pending=queue.pending())
                    registered=False
                    if once: raise
                    stop.wait(retry); retry=min(retry*2,900)
        finally:
            if registered and not once:
                # Best effort only. SQLite retains any data not explicitly acknowledged.
                try: flush(client,config,queue)
                except Exception: pass
