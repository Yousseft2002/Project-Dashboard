import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from tracker.github_dashboard import Dashboard, RemoteError, reminders

class GitHubDashboardTests(unittest.TestCase):
    def setUp(self):
        folder = Path(__file__).resolve().parent.parent / 'data' / 'tests'
        folder.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.tmp.cleanup)
        self.app = Dashboard({'TRACKER_DATA_DIR': self.tmp.name, 'GITHUB_REPOSITORIES': 'me/project',
                              'GITHUB_READ_TOKEN': 'never-render-this', 'GITHUB_CLIENT_SECRET': 'secret'})
        self.headers = {'host': '127.0.0.1:8765', 'origin': 'http://127.0.0.1:8765'}
        with self.app.db() as db:
            db.execute('INSERT INTO sessions VALUES (?,?)', (self.app.digest('test-session'), time.time()+60))
        self.auth = {**self.headers, 'cookie': 'pt_session=test-session'}
    def call(self, method, path, headers=None, raw=b''):
        return self.app.dispatch(method,path,self.auth if headers is None else headers,raw)
    def test_private_routes_require_session(self):
        for path in ['/api/projects','/api/commit?repo=me/project&sha='+'a'*40,'/api/summary?repo=me/project']:
            self.assertEqual(self.call('GET',path,self.headers)[0],401)
    def test_no_legacy_collection_routes(self):
        for path in ['/api/scan','/api/collector/register','/api/agent/v1/register','/api/open-folder','/api/analyze']:
            self.assertEqual(self.call('POST',path)[0],404)
    def test_cross_origin_and_host_rejected(self):
        self.assertEqual(self.call('POST','/api/work?repo=me/project',{**self.auth,'origin':'https://evil.example'})[0],403)
        self.assertEqual(self.call('GET','/api/projects',{**self.auth,'host':'evil.example'})[0],400)
        self.assertEqual(self.call('POST','/api/logout',{k:v for k,v in self.auth.items() if k!='origin'})[0],403)
    def test_repository_allowlist_and_commit_validation(self):
        self.assertEqual(self.call('GET','/api/commit?repo=me/other&sha='+'a'*40)[0],404)
        self.assertEqual(self.call('GET','/api/commit?repo=me/project&sha=../../user')[0],400)
        with self.assertRaises(ValueError): self.app.project('me/other')
    def test_tokens_never_in_session_or_frontend(self):
        for path in ['/api/session','/','/dashboard.js']:
            status, headers, raw=self.call('GET',path)
            self.assertEqual(status,200)
            self.assertNotIn(b'never-render-this',raw)
            self.assertEqual(headers['Cache-Control'],'no-store')
    def test_oauth_state_must_match_and_be_one_use(self):
        self.app.env.update(GITHUB_CLIENT_ID='client',GITHUB_OWNER_ID='1')
        status,headers,_=self.call('GET','/auth/github')
        self.assertEqual(status,302)
        self.assertIn('code_challenge_method=S256',headers['Location'])
        self.assertNotIn('scope=repo',headers['Location'])
        state=headers['Set-Cookie'].split(';')[0].split('=',1)[1]
        callback='/auth/callback?state='+state+'&code=code'
        self.assertEqual(self.call('GET',callback)[0],403)
        oauthheaders={**self.headers,'cookie':'pt_oauth='+state}
        with patch('tracker.github_dashboard.remote',side_effect=[{'access_token':'discarded'}, {'id':2}]):
            self.assertEqual(self.call('GET',callback,oauthheaders)[0],403)
        self.assertEqual(self.call('GET',callback,oauthheaders)[0],403)
    def test_owner_login_and_logout(self):
        self.app.env.update(GITHUB_CLIENT_ID='client',GITHUB_OWNER_ID='1')
        _,headers,_=self.call('GET','/auth/github')
        state=headers['Set-Cookie'].split(';')[0].split('=',1)[1]
        with patch('tracker.github_dashboard.remote',side_effect=[{'access_token':'discarded'},{'id':1}]):
            status,headers,_=self.call('GET','/auth/callback?state='+state+'&code=code',{**self.headers,'cookie':'pt_oauth='+state})
        self.assertEqual(status,302)
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        logged={**self.headers,'cookie':headers['Set-Cookie'].split(';')[0]}
        self.assertTrue(json.loads(self.call('GET','/api/session',logged)[2])['authenticated'])
        self.assertEqual(self.call('POST','/api/logout',logged)[0],200)
        self.assertEqual(self.call('GET','/api/projects',logged)[0],401)
    def test_partial_failures_and_empty_repository(self):
        def github(path):
            if path=='/repos/me/project': return {'name':'Project','default_branch':'main','private':True}
            if '/commits?' in path: raise RemoteError(409)
            raise RemoteError(403)
        with patch.object(self.app,'github',side_effect=github):
            p=self.app.project('me/project')
        self.assertEqual(p['commits'],[])
        self.assertEqual(len(p['warnings']),3)
        with patch.object(self.app,'project',side_effect=RemoteError(403)):
            body=json.loads(self.call('GET','/api/projects')[2])
        self.assertEqual(body['projects'],[])
        self.assertEqual(body['errors'][0]['status'],403)
    def test_work_signal_snooze_and_ai_opt_in(self):
        self.assertEqual(self.call('POST','/api/work?repo=me/project')[0],200)
        self.assertEqual(self.call('POST','/api/snooze?repo=me/project')[0],200)
        self.assertEqual(self.call('POST','/api/summary?repo=me/project')[0],409)
    def test_request_limits(self):
        self.assertEqual(self.call('POST','/api/work?repo=me/project',raw=b'x'*4097)[0],413)
        self.assertEqual(self.call('DELETE','/api/projects')[0],405)
        for _ in range(61): result=self.call('GET','/api/nope')
        self.assertEqual(result[0],429)
    def test_production_fails_closed(self):
        with self.assertRaises(ValueError): Dashboard({'APP_ENV':'production'})
        with self.assertRaises(ValueError): Dashboard({'APP_ENV':'production','APP_ORIGIN':'https://tracker.example'})
    def test_reminders_require_recent_explicit_work_and_resolve(self):
        now=time.time(); p={'id':'me/project','name':'Project','commits':[]}
        self.assertEqual(reminders(p,0,0,now),[])
        self.assertEqual(reminders(p,now-100,0,now),[])
        self.assertEqual(len(reminders(p,now-4000,0,now)),1)
        self.assertEqual(reminders(p,now-4000,now+100,now),[])
        self.assertEqual(reminders(p,now-90000,0,now),[])
        p['commits']=[{'date':datetime.fromtimestamp(now-10,timezone.utc).isoformat()}]
        self.assertEqual(reminders(p,now-4000,0,now),[])

    def test_commit_response_never_contains_patch(self):
        commit={'commit':{'message':'Fix navigation'},'files':[{'filename':'app.js','status':'modified','additions':3,'deletions':1,'patch':'sensitive source'}],'stats':{'total':4}}
        with patch.object(self.app,'github',return_value=commit):
            status,_,body=self.call('GET','/api/commit?repo=me/project&sha='+'a'*40)
        self.assertEqual(status,200)
        self.assertNotIn(b'sensitive source',body)
        self.assertNotIn('patch',json.loads(body)['files'][0])

    def test_ai_receives_only_bounded_evidence_when_explicitly_enabled(self):
        self.app.env.update(AI_SUMMARIES_ENABLED='true',OPENAI_API_KEY='api-secret')
        project={'commits':[{'sha':'a'*40,'message':'Fix authentication'}]}
        detail={'files':[{'filename':'auth.py','additions':5,'deletions':2,'patch':'private patch'}]}
        with patch.object(self.app,'project',return_value=project), patch.object(self.app,'github',return_value=detail), patch('tracker.github_dashboard.remote',return_value={'choices':[{'message':{'content':'Updated auth (aaaaaaa).'}}]}) as upstream:
            status,_,body=self.call('POST','/api/summary?repo=me/project')
        self.assertEqual(status,200)
        self.assertNotIn('private patch',json.dumps(upstream.call_args.args[2]))
        self.assertNotIn(b'api-secret',body)
        self.assertIn(b'aaaaaaa',body)

    def test_asgi_enforces_same_private_boundary(self):
        from tracker.github_dashboard import app
        events=[]
        async def receive(): return {'type':'http.request','body':b'','more_body':False}
        async def send(event): events.append(event)
        scope={'type':'http','method':'GET','path':'/api/projects','query_string':b'','headers':[(b'host',b'127.0.0.1:8765')]}
        async def immediate(function,*args): return function(*args)
        # Drive the adapter without a network-backed Windows event loop.
        with patch('tracker.github_dashboard.dashboard',return_value=self.app), patch('tracker.github_dashboard.asyncio.to_thread',side_effect=immediate):
            with self.assertRaises(StopIteration): app(scope,receive,send).send(None)
        self.assertEqual(events[0]['status'],401)
        self.assertNotIn(b'never-render-this',events[1]['body'])

if __name__=='__main__': unittest.main()
