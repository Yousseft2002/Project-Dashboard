import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import collector
from tracker.db import DB
from tracker.central import CentralStore
from test_http_pipeline import server

class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old_db,self.old_store=server.db,server.central
        server.db=DB(Path(self.tmp.name)/'db.sqlite')
        server.central=CentralStore(server.db)
        self.httpd=server.TrackerServer(('127.0.0.1',0),server.Handler)
        self.httpd.cloud=True
        self.httpd.auth_required=True
        self.httpd.expected_host='127.0.0.1'
        threading.Thread(target=self.httpd.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.httpd.server_port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.db,server.central=self.old_db,self.old_store
        self.tmp.cleanup()

    def test_registration_heartbeat_before_scanning_and_readback(self):
        credential=server.central.register('Desktop')
        client=collector.Client(self.url,credential['token'])
        config={'device_name':'Desktop','installation_id':'installation-one','workspaces':[]}
        config_path=Path(self.tmp.name)/'collector.config.json'
        state={}
        collector.connect(client,config,config_path,state,config_path.with_suffix('.state.json'))
        devices=server.central.snapshot()['devices']
        self.assertEqual(devices[0]['status'],'online')
        self.assertEqual(devices[0]['collector_version'],collector.VERSION)
        self.assertEqual(len(server.central.snapshot()['projects']),0)
        project={'name':'real metadata test','path':'C:/work/repo','repository':'https://github.com/test/repo','commits':[{'sha':'b'*40,'timestamp':collector.utc_now()}]}
        result=collector.sync(client,config,{'projects':[project]},state,config_path.with_suffix('.state.json'))
        self.assertEqual(result['created'],1)
        self.assertEqual(client.status()['projects'][0]['latest_commit']['sha'],'b'*40)
        repeat=client.upload('Desktop',{'projects':[project]})
        self.assertEqual(repeat['activity_duplicates'],1)
        self.assertEqual(repeat['activity_accepted'],0)
        reloaded=CentralStore(DB(server.db.path))
        self.assertEqual(len(reloaded.snapshot()['projects']),1)

    def test_pairing_does_not_grant_access_until_owner_approval(self):
        client=collector.Client(self.url,'')
        token='test-credential-for-local-fixture-only'
        secret='test-pairing-secret-for-local-fixture-only'
        started=client.request('/api/collector/pair/start',{'secret_hash':hashlib.sha256(secret.encode()).hexdigest(),'token_hash':hashlib.sha256(token.encode()).hexdigest(),'installation_id':'fixture-installation','device_name':'Laptop'},authenticated=False)
        claimant=collector.Client(self.url,secret)
        self.assertFalse(claimant.request('/api/collector/pair/claim',{})['approved'])
        with self.assertRaises(collector.CollectorError):
            collector.Client(self.url,token).status()
        with self.assertRaises(collector.CollectorError):
            client.request('/api/integrations/pair/approve',{'code':started['pairing_code']},authenticated=False)
        approved=server.central.pairing_approve(started['pairing_code'])
        self.assertEqual(claimant.request('/api/collector/pair/claim',{})['device_id'],approved['device_id'])
        self.assertEqual(collector.Client(self.url,token).status()['device']['id'],approved['device_id'])
        with server.db.conn() as c:
            self.assertNotIn(token,str([tuple(r) for r in c.execute('SELECT * FROM devices')]))

    def test_wrong_device_or_reused_installation_fails(self):
        credential=server.central.register('Laptop')
        client=collector.Client(self.url,credential['token'])
        client.register({'device_name':'Laptop','installation_id':'first'})
        with self.assertRaises(collector.CollectorError):
            client.register({'device_name':'Laptop','installation_id':'second'})
        with self.assertRaises(collector.CollectorError):
            client.heartbeat('Desktop')

class ClientValidationTests(unittest.TestCase):
    def test_production_target_requires_explicit_local_mode(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(collector.server_url({}),collector.PRODUCTION_URL)
            for url in ('http://localhost:8765','https://127.0.0.1:8766','http://0.0.0.0:8765','https://example.com:8765','http://example.com','https://server.local'):
                with self.assertRaises(collector.CollectorError): collector.server_url({'server':url})
            self.assertEqual(collector.server_url({'server':'http://127.0.0.1:8765'},True),'http://127.0.0.1:8765')
        with patch.dict(os.environ,{'PROJECT_PLANNER_URL':collector.PRODUCTION_URL}):
            self.assertEqual(collector.server_url({'server':'http://localhost:8765'}),collector.PRODUCTION_URL)

    def test_webpage_is_not_success(self):
        client=collector.Client(collector.PRODUCTION_URL,'fixture-token')
        response=MagicMock()
        response.__enter__.return_value=response
        response.status=200
        response.headers.get_content_type.return_value='text/html'
        with patch.object(client.opener,'open',return_value=response):
            with self.assertRaises(collector.CollectorError): client.health()

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_protected_token_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config={}
            path=Path(tmp)/'collector.config.json'
            token='local-fixture-secret-not-for-production'
            collector.protect_token(token,config,path)
            self.assertNotIn(token,Path(config['token_file']).read_text())
            with patch.dict(os.environ,{'COLLECTOR_TOKEN':''}):
                self.assertTrue(collector.load_token(config,path)==token)

if __name__=='__main__': unittest.main()
