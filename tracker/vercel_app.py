"""ASGI cloud HTTP adapter. Vercel owns the listener and process lifecycle."""
import hmac
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, Response
from starlette.concurrency import run_in_threadpool
from .central import CentralStore
from .cloud_http import CloudAuth, agent_operation, owner_operation
from . import security

ROOT=Path(__file__).resolve().parent.parent
HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
 'Referrer-Policy':'no-referrer','Cross-Origin-Resource-Policy':'same-origin',
 'Cross-Origin-Opener-Policy':'same-origin','Permissions-Policy':'camera=(), microphone=(), geolocation=(), payment=()',
 'Strict-Transport-Security':'max-age=31536000; includeSubDomains',
 'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"}

def create_app(database_override=None,hosts=None,password=None):
    application=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    lock=threading.Lock(); resources=[]
    def configured_hosts():
        values=hosts if hosts is not None else [os.environ.get(key,'') for key in ('PUBLIC_HOSTNAME','VERCEL_PROJECT_PRODUCTION_URL','VERCEL_URL')]
        return {value.lower().rstrip('.') for value in values if re.fullmatch(r'[a-zA-Z0-9.-]+(?::\d+)?',value)}
    def initialize():
        with lock:
            if not resources:
                secret=password if password is not None else os.environ.get('APP_PASSWORD','')
                if len(secret)<16: raise ValueError('APP_PASSWORD must contain at least 16 characters')
                from .postgres import database
                db=database_override if database_override is not None else database(ROOT/'data'/'unused.sqlite',require_postgres=True)
                store=CentralStore(db)
                from .agent_api import initialize as agent_initialize
                agent_initialize(db)
                resources.extend((db,store,CloudAuth(db),secret))
        return resources
    def reply(status,body,headers=None): return JSONResponse(body,status_code=status,headers=headers)
    def operation(request,body):
        db,store,auth,secret=initialize()
        path=request.url.path; method=request.method
        if path in ('/health','/api/health') and method=='GET':
            with db.conn() as c: c.execute('SELECT 1').fetchone()
            return reply(200,{'status':'ok','service':'project-planner','collector_api_version':2,'agent_api_version':1,
                              'http_adapter':'fastapi','database':getattr(db,'backend','sqlite-test')})
        token=security.cookie_from(request.headers.get('cookie'))
        if path=='/api/login' and method=='POST':
            # No arbitrary forwarded IP headers are trusted. Global PostgreSQL
            # limits protect all instances, including when proxy peers share an IP.
            if auth.limited('login-global',25,600): return reply(429,{'error':'Too many login attempts'},{'Retry-After':'600'})
            if not isinstance(body.get('code'),str) or not hmac.compare_digest(body['code'].encode(),secret.encode()): return reply(401,{'error':'Incorrect password.'})
            session=auth.session()
            return reply(200,{'ok':True},{'Set-Cookie':f'{security.COOKIE}={session}; Path=/; Max-Age={security.SESSION_DAYS*86400}; HttpOnly; SameSite=Strict; Secure'})
        if path=='/api/logout' and method=='POST':
            auth.logout(token)
            return reply(200,{'ok':True},{'Set-Cookie':f'{security.COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict; Secure'})
        pairing=re.fullmatch(r'/api/(?:agent/v1|collector)/pair/(start|claim)',path)
        if pairing and method=='POST':
            if auth.limited('pair-global',60): return reply(429,{'error':'Pairing rate limit reached'},{'Retry-After':'60'})
            authorization=request.headers.get('authorization','')
            result=store.pairing_start(body) if pairing[1]=='start' else store.pairing_claim(authorization[7:] if authorization.startswith('Bearer ') else '')
            return reply(200,result)
        if path.startswith('/api/agent/v1/'):
            status,result,headers=agent_operation(store,method,path[len('/api/agent/v1/'):],request.headers.get('authorization',''),body,
                limiter=lambda device: auth.limited('agent:'+device,60))
            return reply(status,result,headers)
        if path.startswith('/api/collector/'):
            endpoint=path[len('/api/collector/'):]
            if (method,endpoint) not in {('POST','register'),('POST','heartbeat'),('POST','projects'),('GET','status')}:
                return reply(404,{'error':'not found'})
            authorization=request.headers.get('authorization','')
            device=store.authenticate(authorization[7:] if authorization.startswith('Bearer ') else '')
            if not device: return reply(401,{'error':'Invalid or revoked collector credential'})
            if auth.limited('agent:'+device,60): return reply(429,{'error':'Collector rate limit reached'},{'Retry-After':'60'})
            if body.get('device_id',device)!=device: raise ValueError('Device identity mismatch')
            function={'register':store.register_collector,'heartbeat':store.heartbeat,'projects':store.ingest,'status':store.collector_status}[endpoint]
            return reply(200,function(device,body) if endpoint in ('register','projects') else function(device))
        # Frontend assets contain no owner data. Build publishes these to the CDN;
        # this fallback makes the same app directly testable with ASGI.
        relative=path.lstrip('/'); source=(ROOT/'static'/relative).resolve()
        if method=='GET' and source.is_relative_to((ROOT/'static').resolve()) and source.is_file() and source.suffix in {'.js','.css','.svg','.png','.ico','.webp'}:
            if len(Path(relative).parts)==1 or Path(relative).parts[0]=='js': return FileResponse(source)
        if path=='/login' and method=='GET':
            return RedirectResponse('/',status_code=302) if auth.valid(token) else FileResponse(ROOT/'static/login.html')
        if not auth.valid(token):
            return reply(401,{'error':'login required'}) if path.startswith('/api/') else RedirectResponse('/login',status_code=302)
        if method=='GET' and path=='/': return FileResponse(ROOT/'static/index.html')
        if method=='GET' and re.fullmatch(r'/previews/[a-f0-9]{16}\.png',path):
            from .dashboard_transfer import initialize as preview_initialize
            preview_initialize(db)
            with db.conn() as c: row=c.execute('SELECT data FROM dashboard_import_previews WHERE name=?',(path.rsplit('/',1)[1],)).fetchone()
            return Response(bytes(row['data']),media_type='image/png') if row else reply(404,{'error':'not found'})
        if path.startswith('/api/'):
            status,result=owner_operation(db,store,method,path,body)
            return reply(status,result)
        return reply(404,{'error':'not found'})

    @application.middleware('http')
    async def guard(request,call_next):
        host=request.headers.get('host','').lower().rstrip('.')
        origin=request.headers.get('origin')
        if host not in configured_hosts(): response=reply(400,{'error':'unexpected host'})
        elif request.headers.get('sec-fetch-site','same-origin') not in ('same-origin','none') and (request.url.path.startswith('/api/') or request.method!='GET'):
            response=reply(403,{'error':'cross-site request blocked'})
        elif origin and (urlsplit(origin).scheme!='https' or urlsplit(origin).netloc.lower()!=host): response=reply(403,{'error':'forbidden origin'})
        else: response=await call_next(request)
        for key,value in HEADERS.items(): response.headers[key]=value
        return response

    @application.api_route('/{path:path}',methods=['GET','POST','PATCH','DELETE','PUT','OPTIONS'])
    async def dispatch(request:Request,path:str):
        maximum=2_000_000 if request.url.path.startswith('/api/agent/') else 5_000_000 if request.url.path.startswith('/api/collector/') else 4_000_000
        try:
            length=int(request.headers.get('content-length','0'))
            if length<0: return reply(400,{'error':'bad request'})
            if length>maximum: return reply(413,{'error':'request too large'})
            raw=bytearray()
            async for chunk in request.stream():
                if len(raw)+len(chunk)>maximum: return reply(413,{'error':'request too large'})
                raw.extend(chunk)
            body=json.loads(raw) if raw else {}
            if not isinstance(body,dict): return reply(400,{'error':'Expected a JSON object'})
            return await run_in_threadpool(operation,request,body)
        except (ValueError,TypeError): return reply(400,{'error':'Invalid request or missing secure deployment configuration'})
        except Exception: return reply(503,{'error':'Cloud database operation unavailable'})
    return application

app=create_app()
