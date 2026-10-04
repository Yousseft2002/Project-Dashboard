import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

# Import the server against an isolated DB, never the owner's data/ directory.
TEMP = tempfile.TemporaryDirectory()
os.environ['TRACKER_DATA_DIR'] = TEMP.name
from tracker import server

class HTTPPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.TrackerServer(('127.0.0.1',0),server.Handler)
        cls.httpd.cloud = True
        cls.httpd.auth_required = True
        cls.httpd.expected_host = '127.0.0.1'
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.httpd.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        TEMP.cleanup()

    def request(self,path,body=None,token=None,cookie=None):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        if cookie: headers['Cookie']=cookie
        request=urllib.request.Request(self.url+path,json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(request) as r:
            return json.loads(r.read())

    def test_secure_pipeline(self):
        from tracker import security
        device=server.central.register('HTTP-device')
        cookie=security.COOKIE+'='+security.new_session()
        for endpoint in ('/api/state','/api/debug','/api/integrations'):
            with self.assertRaises(urllib.error.HTTPError) as err:
                self.request(endpoint)
            self.assertEqual(err.exception.code,401)
            err.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/collector/projects', {'projects':[]}, token='bad')
        self.assertEqual(err.exception.code,401)
        err.exception.close()
        self.request('/api/collector/heartbeat',{},token=device['token'])
        project={'name':'HTTP test','path':'C:/work/http-test','repository':'git@github.com:test/http.git','last_activity':server.datetime.now(server.timezone.utc).isoformat()}
        self.request('/api/collector/projects',{'projects':[project],'sources':[{'name':'workspace','status':'connected'}]},token=device['token'])
        payload=self.request('/api/state',cookie=cookie)
        self.assertEqual(len(payload['projects']),1)
        self.assertEqual(payload['projects'][0]['name'],'HTTP test')
        self.assertFalse(payload['projects'][0]['facts']['local'])
        self.assertEqual(self.request('/api/debug',cookie=cookie)['database'],'ok')
        pid=payload['projects'][0]['id']
        self.request('/api/integrations/instruction',{'project_id':pid,'text':'Finish human-requested workflow verification'},cookie=cookie)
        updated=self.request('/api/state',cookie=cookie)
        self.assertEqual(updated['projects'][0]['tasks'][0]['source'],'user')
        self.assertTrue(updated['planner']['directives'])
        self.request('/api/integrations/sync',{},cookie=cookie)
        self.assertTrue(self.request('/api/collector/heartbeat',{},token=device['token'])['sync_requested'])
        self.request('/api/collector/projects',{'projects':[project]},token=device['token'])
        self.assertFalse(self.request('/api/collector/heartbeat',{},token=device['token'])['sync_requested'])
        # Collector credentials have no owner/debug authorization.
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/debug',token=device['token'])
        err.exception.close()

if __name__=='__main__': unittest.main()
