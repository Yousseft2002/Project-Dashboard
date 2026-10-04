"""Read-only collector: python collector.py --config collector.config.json [--once|--dry-run]."""
import argparse
import json
import os
import time
import shutil
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from tracker.connectors.local_workspace import discover
from tracker.central import repository
from tracker.connectors.ai_metadata import collect_sessions

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A server redirect must never forward the collector credential to another host.
        raise urllib.error.HTTPError(req.full_url, code, 'Collector redirects refused', headers, fp)

def send(server, token, endpoint, body):
    req = urllib.request.Request(server + '/api/collector/' + endpoint, json.dumps(body).encode(), headers={'Content-Type':'application/json', 'Authorization':'Bearer '+token}, method='POST')
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as res:
        return json.loads(res.read())

def collect(config):
    projects, warnings = discover(config['workspaces'], config.get('ignore', []), config.get('max_depth', 5))
    for p in projects:
        remote = repository(p['repository'])
        p['repository'] = 'https://' + remote if remote else ''
    sources = [{'name':'workspace','status':'connected'}, {'name':'git','status':'connected'}, {'name':'vscode','status':'inferred'}, {'name':'claude','status':'not_configured'}, {'name':'codex','status':'not_configured'}, {'name':'github','status':'not_configured'}, {'name':'render','status':'not_configured'}]
    if not shutil.which('git'):
        sources[1]['status'] = 'unavailable'
    if config.get('ai_metadata', True):
        reports = collect_sessions(projects, config.get('session_roots'))
        sources = [s for s in sources if s['name'] not in ('claude','codex')] + reports
    if warnings:
        sources[0]['status'] = 'error'
    return {'projects':projects, 'sources':sources}, warnings

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='collector.config.json')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    if not isinstance(config.get('workspaces'), list) or not config['workspaces'] or not all(isinstance(x,str) for x in config['workspaces']):
        parser.error('Configure one or more workspace folders')
    server = str(config.get('server','')).rstrip('/')
    u = urlsplit(server)
    if u.username or u.password or u.query or u.fragment or u.path or not (u.scheme == 'https' or (u.scheme == 'http' and u.hostname in ('localhost','127.0.0.1'))):
        parser.error('Server must be an HTTPS origin (HTTP is allowed only on loopback)')
    token = os.environ.get('COLLECTOR_TOKEN','')
    if not args.dry_run and not token:
        parser.error('Set COLLECTOR_TOKEN in the environment')
    interval = max(60, int(config.get('sync_seconds',300)))
    next_sync = 0
    while True:
        try:
            heartbeat = {} if args.dry_run else send(server,token,'heartbeat',{})
            if args.once or args.dry_run or time.monotonic() >= next_sync or heartbeat.get('sync_requested'):
                payload, warnings = collect(config)
                if args.dry_run:
                    print(json.dumps({'projects':len(payload['projects']), 'sources':payload['sources'], 'warnings':warnings}, indent=2))
                    return
                result = send(server,token,'projects',payload)
                print('Sync complete:', result['projects'], 'projects at', result['last_synced'], flush=True)
                for warning in warnings:
                    print(warning, flush=True)
                next_sync = time.monotonic() + interval
            if args.once:
                return
        except (OSError, ValueError, urllib.error.URLError) as e:
            # No response bodies, credentials or request payloads in logs.
            print('Sync failed:', 'HTTP '+str(e.code) if isinstance(e, urllib.error.HTTPError) else type(e).__name__, flush=True)
            if args.once:
                raise SystemExit(1)
        time.sleep(30)

if __name__ == '__main__':
    main()
