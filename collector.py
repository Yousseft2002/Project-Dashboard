"""Production collector: setup_collector.ps1, then python collector.py [test|status]."""
import argparse
import hashlib
import ipaddress
import json
import os
import platform
import shutil
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from tracker.connectors.local_workspace import discover, inspect, IGNORE
from tracker.central import repository

PRODUCTION_URL = 'https://project-dashboard-0d02.onrender.com'
VERSION = '2.0.0'
BASE = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE / 'collector.config.json'

class CollectorError(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CollectorError('Server redirected the API request. Credentials were not forwarded; check PROJECT_PLANNER_URL.')

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def server_url(config, local_development=False):
    server = str(os.environ.get('PROJECT_PLANNER_URL') or config.get('server') or PRODUCTION_URL).strip().rstrip('/')
    try:
        u=urlsplit(server)
        port=u.port
    except ValueError:
        raise CollectorError('Invalid server URL')
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.path:
        raise CollectorError('Server must be an origin without credentials, paths, queries or fragments')
    host=u.hostname.lower()
    try:
        local=not ipaddress.ip_address(host).is_global
    except ValueError:
        local=host in ('localhost','localhost.localdomain') or host.endswith(('.localhost','.local')) or '.' not in host
    if host in ('0.0.0.0','::'):
        raise CollectorError('Unspecified addresses cannot be collector targets')
    if local or port in (8765,8766):
        if not local_development:
            raise CollectorError('Local targets and ports 8765/8766 require --local-development. Production default is '+PRODUCTION_URL)
        if host not in ('localhost','127.0.0.1','::1'):
            raise CollectorError('Local development mode supports loopback only')
    if u.scheme!='https' and not (local_development and u.scheme=='http' and host in ('localhost','127.0.0.1','::1')):
        raise CollectorError('Production collector requires HTTPS')
    return server

def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}
    except (OSError,ValueError):
        raise CollectorError('Cannot read local configuration/state JSON: '+str(path))

def write_json(path, data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2),encoding='utf-8')
    temp.replace(path)

def load_token(config, config_path):
    if os.environ.get('COLLECTOR_TOKEN'):
        return os.environ['COLLECTOR_TOKEN'].strip()
    token_file=config.get('token_file')
    if not token_file:
        return ''
    token_path=Path(token_file)
    if not token_path.is_absolute():
        token_path=Path(config_path).parent/token_path
    if os.name!='nt' or not token_path.is_file():
        return ''
    env=dict(os.environ,PROJECT_PLANNER_TOKEN_FILE=str(token_path))
    command="try { $secret = (Get-Content -Raw -LiteralPath $env:PROJECT_PLANNER_TOKEN_FILE).Trim() | ConvertTo-SecureString -ErrorAction Stop; [System.Net.NetworkCredential]::new('', $secret).Password } catch { exit 1 }"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],env=env,capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise CollectorError('Protected collector token could not be opened. Run setup again as the same Windows user.')
    return result.stdout.strip()

def protect_token(token,config,config_path):
    if os.name!='nt':
        raise CollectorError('Automatic protected token storage requires Windows; use COLLECTOR_TOKEN on other platforms')
    token_path=Path(config_path).with_name('collector.token.dpapi')
    command="$ErrorActionPreference = 'Stop'; $secret = [Console]::In.ReadToEnd() | ConvertTo-SecureString -AsPlainText -Force; ConvertFrom-SecureString -SecureString $secret | Set-Content -LiteralPath $env:PROJECT_PLANNER_TOKEN_FILE -Encoding ASCII"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],input=token,text=True,capture_output=True,env=dict(os.environ,PROJECT_PLANNER_TOKEN_FILE=str(token_path)),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
    if result.returncode or not token_path.is_file():
        raise CollectorError('Could not protect the collector token with Windows DPAPI')
    config['token_file']=str(token_path)
    write_json(config_path,config)

def pair(client,config,config_path):
    client.health()
    token=secrets.token_urlsafe(32)
    secret=secrets.token_urlsafe(32)
    request={'secret_hash':hashlib.sha256(secret.encode()).hexdigest(),'token_hash':hashlib.sha256(token.encode()).hexdigest(),'installation_id':config['installation_id'],'device_name':config['device_name'],'platform':platform.system(),'collector_version':VERSION}
    result=client.request('/api/collector/pair/start',request,authenticated=False)
    if result.get('ok') is not True or not isinstance(result.get('pairing_code'),str):
        raise CollectorError('Pairing request not accepted')
    print('Pairing approval code (not a collector token): '+result['pairing_code'],flush=True)
    print('Open '+client.server+'/#/integrations and approve that exact code for '+config['device_name']+'.',flush=True)
    print('Waiting up to 10 minutes. Collector secrets remain on this computer.',flush=True)
    poll=Client(client.server,secret)
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        status=poll.request('/api/collector/pair/claim',{})
        if status.get('ok') is not True: raise CollectorError('Pairing status invalid')
        if status.get('approved') is True and status.get('device_id'):
            config['device_id']=status['device_id']
            protect_token(token,config,config_path)
            client.token=token
            print('Pairing approved. Collector credential saved with Windows DPAPI.',flush=True)
            return
        time.sleep(2)
    raise CollectorError('Pairing approval timed out. Run setup again.')

def http_error(error):
    if isinstance(error,urllib.error.HTTPError):
        labels={400:'Server rejected collector metadata. Check device identity, paths and timestamps.',401:'Collector authentication failed. Use a token issued by this production server.',403:'Collector request forbidden by the server.',404:'Collector endpoint not found. Production server may be running an incompatible version.',429:'Server rate limit reached. Retry later.',500:'Production server encountered an ingestion error.',502:'Production server is temporarily unavailable.',503:'Production server is temporarily unavailable.'}
        code=error.code
        error.close()
        return str(code)+' — '+labels.get(code,'Collector API request failed.')
    reason=error.reason if isinstance(error,urllib.error.URLError) else error
    if isinstance(reason,socket.gaierror):
        return 'Render hostname could not be resolved.'
    if isinstance(reason,(TimeoutError,socket.timeout)):
        return 'Cannot reach Project Planner server: connection timed out.'
    return 'Cannot reach Project Planner server. Check DNS, network and HTTPS certificates.'

class Client:
    def __init__(self,server,token):
        self.server,self.token=server,token
        self.opener=urllib.request.build_opener(NoRedirect())

    def request(self,path,body=None,authenticated=True):
        headers={'Accept':'application/json'}
        if authenticated:
            if not self.token:
                raise CollectorError('Authentication missing. Run setup_collector.ps1 or set COLLECTOR_TOKEN.')
            headers['Authorization']='Bearer '+self.token
        if body is not None: headers['Content-Type']='application/json'
        req=urllib.request.Request(self.server+path,json.dumps(body).encode() if body is not None else None,headers=headers,method='POST' if body is not None else 'GET')
        try:
            with self.opener.open(req,timeout=90) as response:
                if response.status!=200 or response.headers.get_content_type()!='application/json':
                    raise CollectorError('Unexpected API response. A webpage/login page is not proof of a collector connection.')
                raw=response.read(1_000_001)
                if len(raw)>1_000_000: raise CollectorError('Collector API response too large')
                try: result=json.loads(raw)
                except ValueError: raise CollectorError('Server returned invalid JSON')
                if not isinstance(result,dict): raise CollectorError('Server returned an incompatible API response')
                return result
        except (OSError,urllib.error.URLError) as error:
            raise CollectorError(http_error(error)) from None

    def health(self):
        result=self.request('/api/health',authenticated=False)
        if result.get('status')!='ok' or result.get('service')!='project-planner' or result.get('collector_api_version',0)<2:
            raise CollectorError('Production server is running an incompatible collector API. Deploy collector API version 2.')
        return result

    def register(self,config):
        body={'device_name':config['device_name'],'platform':platform.system(),'collector_version':VERSION,'installation_id':config['installation_id']}
        if config.get('device_id'): body['device_id']=config['device_id']
        result=self.request('/api/collector/register',body)
        if result.get('ok') is not True or result.get('registered') is not True or not result.get('device_id') or result.get('database_write') is not True:
            raise CollectorError('Device registration was not confirmed by the database')
        return result

    def heartbeat(self,device):
        result=self.request('/api/collector/heartbeat',{'device_id':device})
        if result.get('ok') is not True or result.get('device_id')!=device or result.get('database_write') is not True or not result.get('last_seen'):
            raise CollectorError('Heartbeat database write was not confirmed')
        return result

    def status(self):
        result=self.request('/api/collector/status')
        if result.get('ok') is not True or not isinstance(result.get('device'),dict) or not isinstance(result.get('projects'),list):
            raise CollectorError('Collector status response is incompatible')
        return result

    def upload(self,device,payload):
        result=self.request('/api/collector/projects',dict(payload,device_id=device))
        if result.get('ok') is not True or result.get('device_id')!=device or result.get('database_write') is not True or result.get('projects')!=len(payload['projects']) or not result.get('last_synced') or not isinstance(result.get('project_ids'),list) or len(result['project_ids'])!=len(payload['projects']):
            raise CollectorError('Server did not confirm the project batch database write')
        return result

def collect(config):
    projects,warnings=discover(config['workspaces'],config.get('ignore',[]),config.get('max_depth',5))
    for p in projects:
        remote=repository(p['repository'])
        p['repository']='https://'+remote if remote else ''
    sources=[{'name':'workspace','status':'error' if warnings else 'connected'},{'name':'git','status':'connected' if shutil.which('git') else 'unavailable'}]
    return {'projects':projects,'sources':sources},warnings

def single_project(path,config):
    path=Path(path).expanduser().resolve()
    if not path.is_dir() or not (path/'.git').exists():
        raise CollectorError('Choose one existing Git repository with --project PATH before testing project ingestion')
    p=inspect(path,IGNORE+config.get('ignore',[]))
    if not p['git_observed'] or not p['commits']:
        raise CollectorError('The test repository must have readable Git metadata and at least one commit')
    remote=repository(p['repository'])
    p['repository']='https://'+remote if remote else ''
    return {'projects':[p],'sources':[{'name':'git','status':'connected'}]}

def banner(config,server,token,state):
    print('\nPROJECT PLANNER COLLECTOR',flush=True)
    values=[('Device',config.get('device_name',socket.gethostname())),('Device ID',config.get('device_id','Not registered yet')),('Server',server),('Authentication','Configured' if token else 'Missing'),('Workspace folders',len(config.get('workspaces',[]))),('Projects discovered',state.get('projects_discovered','Not scanned')),('Server connection',state.get('server_connection','Not tested')),('Device registration',state.get('registration','Not tested')),('Last successful sync',state.get('last_sync','Never'))]
    for label,value in values: print(label+': '+str(value),flush=True)

def connect(client,config,config_path,state,state_path):
    state['last_attempt']=utc_now()
    client.health()
    state['server_connection']='Connected'
    print('SERVER TEST: Render reachable; collector API version 2 verified',flush=True)
    registration=client.register(config)
    config['device_id']=registration['device_id']
    write_json(config_path,config)
    state['registration']='Registered'
    print('AUTH TEST: Collector authenticated',flush=True)
    print('DEVICE TEST: Device registered — '+config['device_id'],flush=True)
    heartbeat=client.heartbeat(config['device_id'])
    state.update(last_heartbeat=heartbeat['last_seen'],last_error=None,device_id=config['device_id'])
    write_json(state_path,state)
    status=client.status()
    if status['device'].get('id')!=config['device_id'] or not status['device'].get('last_seen'):
        raise CollectorError('Heartbeat could not be read back from the production database; project ingestion stopped')
    print('DATABASE TEST: Heartbeat persisted and read back; device is online',flush=True)
    return heartbeat

def sync(client,config,payload,state,state_path):
    state.update(projects_discovered=len(payload['projects']),pending_projects=len(payload['projects']),last_attempt=utc_now())
    write_json(state_path,state)
    result=client.upload(config['device_id'],payload)
    readback=client.status()
    received={p['project_id'] for p in readback['projects']}
    if not set(result['project_ids']).issubset(received):
        raise CollectorError('Accepted projects could not be read back from the production database')
    for pid,project in zip(result['project_ids'],payload['projects']):
        saved=next(p for p in readback['projects'] if p['project_id']==pid)
        if project.get('commits') and (saved.get('latest_commit') or {}).get('sha')!=project['commits'][0]['sha']:
            raise CollectorError('Latest Git commit metadata did not match database read-back')
    state.update(last_sync=result['last_synced'],projects_synced=result['projects'],pending_projects=0,last_error=None,project_verified=True)
    write_json(state_path,state)
    print(str(result['projects'])+' projects synchronized; '+str(result.get('activity_accepted',0))+' activity records accepted; '+str(result.get('activity_duplicates',0))+' duplicates',flush=True)
    print('Last successful sync: '+result['last_synced'],flush=True)
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',nargs='?',choices=['run','test','status','suggest','pair'],default='run')
    parser.add_argument('--config',default=str(DEFAULT_CONFIG))
    parser.add_argument('--test',action='store_true')
    parser.add_argument('--project',help='One real Git repository for first ingestion verification')
    parser.add_argument('--heartbeat-only',action='store_true')
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--local-development',action='store_true')
    args=parser.parse_args(argv)
    if args.command=='suggest':
        from tracker.connectors.workspace_suggestions import suggestions
        print(json.dumps(suggestions(),indent=2))
        return 0
    config_path=Path(args.config).resolve()
    state_path=config_path.with_name(config_path.stem+'.state.json')
    state={}
    config={}
    try:
        config=read_json(config_path)
        if not isinstance(config,dict): raise CollectorError('Configuration must be a JSON object')
        config.setdefault('device_name',socket.gethostname())
        config.setdefault('installation_id',str(uuid.uuid4()))
        config.setdefault('workspaces',[])
        if not isinstance(config['workspaces'],list) or not all(isinstance(p,str) for p in config['workspaces']):
            raise CollectorError('Workspaces must be a list of folder paths')
        server=server_url(config,args.local_development)
        state=read_json(state_path)
        if not isinstance(state,dict): raise CollectorError('Collector state must be a JSON object')
        if state.get('server')!=server or state.get('installation_id')!=config['installation_id'] or state.get('device_id')!=config.get('device_id'):
            state={}
        state.update(server=server,installation_id=config['installation_id'],device_id=config.get('device_id'))
        token=load_token(config,config_path)
        banner(config,server,token,state)
        if args.command=='pair':
            write_json(config_path,config)
            client=Client(server,'')
            pair(client,config,config_path)
            connect(client,config,config_path,state,state_path)
            return 0
        if args.dry_run:
            payload,warnings=collect(config)
            print('Projects discovered: '+str(len(payload['projects'])))
            for warning in warnings: print(warning)
            return 0
        client=Client(server,token)
        if args.command=='status':
            client.health()
            result=client.status()
            device=result['device']
            values=[('Server reachable','YES'),('Authenticated','YES'),('Registered','YES'),('Last heartbeat',device.get('last_seen') or 'Never'),('Last sync',device.get('last_sync') or 'Never'),('Projects synchronized',len(result['projects'])),('Pending projects',state.get('pending_projects','Unknown')),('Last error',state.get('last_error') or device.get('last_error') or 'None')]
            for label,value in values: print(label+': '+str(value))
            return 0
        connect(client,config,config_path,state,state_path)
        command='test' if args.test else args.command
        if args.heartbeat_only:
            print('Heartbeat verified. No project scan or upload performed.')
            return 0
        if args.project:
            sync(client,config,single_project(args.project,config),state,state_path)
            print('PROJECT TEST: One real Git repository and commit metadata persisted and read back')
            if command=='test' or args.once: return 0
        elif not state.get('project_verified'):
            raise CollectorError('Heartbeat works. Next run python collector.py test --project "PATH_TO_ONE_GIT_REPOSITORY". Full-workspace ingestion is blocked until this succeeds.')
        if command=='test':
            print('PROJECT TEST: Previous real repository verification recorded for this server/device')
            return 0
        if not config['workspaces']: raise CollectorError('No workspace folders configured. Run setup_collector.ps1.')
        interval=max(60,int(config.get('sync_seconds',300)))
        heartbeat_seconds=max(30,min(120,int(config.get('heartbeat_seconds',60))))
        stop=threading.Event()
        sync_requested=threading.Event()
        def heartbeat_loop():
            while not stop.wait(heartbeat_seconds):
                try:
                    beat=client.heartbeat(config['device_id'])
                    if beat.get('sync_requested'): sync_requested.set()
                except CollectorError as error:
                    print('HEARTBEAT ERROR: '+str(error),flush=True)
        worker=threading.Thread(target=heartbeat_loop,daemon=True)
        if not args.once: worker.start()
        try:
            while True:
                try:
                    client.heartbeat(config['device_id'])
                    payload,warnings=collect(config)
                    print('Projects discovered: '+str(len(payload['projects'])),flush=True)
                    for warning in warnings: print(warning,flush=True)
                    sync(client,config,payload,state,state_path)
                except CollectorError as error:
                    state.update(last_attempt=utc_now(),last_error=str(error))
                    write_json(state_path,state)
                    print('PROJECT SYNC ERROR: '+str(error),flush=True)
                    if args.once: return 1
                if args.once: return 0
                deadline=time.monotonic()+interval
                while time.monotonic()<deadline and not sync_requested.wait(min(1,max(0,deadline-time.monotonic()))): pass
                sync_requested.clear()
        finally:
            stop.set()
    except (CollectorError,OSError,ValueError) as error:
        message=str(error) if isinstance(error,CollectorError) else 'Local collector configuration or filesystem operation failed.'
        state.update(last_attempt=utc_now(),last_error=message,server_connection='Failed')
        try: write_json(state_path,state)
        except OSError: pass
        print('COLLECTOR ERROR: '+message,flush=True)
        return 1
    except KeyboardInterrupt:
        print('\nCollector stopped. Previously synchronized server data is retained.')
        return 0

if __name__=='__main__': raise SystemExit(main())
