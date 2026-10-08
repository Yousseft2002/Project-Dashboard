import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from tracker.db import DB
from tracker.central import CentralStore,now
from tracker.vercel_app import app,create_app
from tracker.postgres import sql,PostgresDB

class VercelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'data')
        self.db=DB(Path(self.temp.name)/'cloud.sqlite')
        self.password='test-password-long-enough'
        self.client=TestClient(create_app(self.db,['testserver'],self.password),base_url='https://testserver')
    def tearDown(self): self.client.close(); self.temp.cleanup()
    def login(self):
        response=self.client.post('/api/login',json={'code':self.password})
        self.assertEqual(response.status_code,200)
        self.assertIn('Secure',response.headers['set-cookie'])
        self.assertIn('HttpOnly',response.headers['set-cookie'])
    def test_app_import_no_database_or_permanent_workers(self):
        self.assertTrue(app)
        code="from unittest.mock import patch\nwith patch('threading.Thread.start',side_effect=AssertionError('worker started')):\n import tracker.vercel_app\n import tracker.server\n assert tracker.vercel_app.app\n assert tracker.server.db.value is None"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
    def test_health_login_cookie_cold_instance_and_logout(self):
        self.assertEqual(self.client.get('/api/health').status_code,200)
        self.assertEqual(self.client.get('/').status_code,200) # redirected to sign-in
        self.assertEqual(self.client.get('/api/state').status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'code':'wrong'}).status_code,401)
        self.login()
        other=TestClient(create_app(self.db,['testserver'],self.password),base_url='https://testserver')
        other.cookies.update(self.client.cookies)
        self.assertEqual(other.get('/api/state').status_code,200)
        self.assertEqual(self.client.post('/api/logout').status_code,200)
        self.assertEqual(other.get('/api/state').status_code,401)
        other.close()
    def test_pairing_ingestion_and_credentials_survive_new_store(self):
        token='device-secret-'+str(uuid.uuid4()); secret='pair-secret-'+str(uuid.uuid4())
        body={'token_hash':hashlib.sha256(token.encode()).hexdigest(),'secret_hash':hashlib.sha256(secret.encode()).hexdigest(),
              'device_name':'YT-Laptop','installation_id':str(uuid.uuid4()),'platform':'Windows'}
        result=self.client.post('/api/agent/v1/pair/start',json=body); self.assertEqual(result.status_code,200)
        code=result.json()['pairing_code']
        claim=lambda: self.client.post('/api/agent/v1/pair/claim',headers={'Authorization':'Bearer '+secret},json={})
        self.assertFalse(claim().json()['approved'])
        self.login(); self.assertEqual(self.client.post('/api/integrations/pair/approve',json={'code':code}).status_code,200)
        device=claim().json()['device_id']; headers={'Authorization':'Bearer '+token}
        register=dict(body,device_id=device,agent_id=str(uuid.uuid4()),collector_version='0.1.0')
        self.assertEqual(self.client.post('/api/agent/v1/register',json=register,headers=headers).status_code,200)
        self.assertEqual(self.client.post('/api/agent/v1/heartbeat',json={'device_id':device},headers=headers).status_code,200)
        project={'name':'MaterialOS','path':'C:/approved/MaterialOS','repository':'https://github.com/test/materialos',
                 'commits':[{'sha':'a'*40,'timestamp':now(),'message':'Real project metadata'}]}
        result=self.client.post('/api/agent/v1/projects',json={'projects':[project]},headers=headers)
        self.assertEqual(result.status_code,200,result.text); pid=result.json()['project_ids'][0]
        event={'event_id':'b'*64,'device_id':device,'project_id':pid,'source':'git','event_type':'commit',
               'timestamp':now(),'summary':'Real project metadata','metadata':{'sha':'a'*40}}
        self.assertEqual(self.client.post('/api/agent/v1/events/batch',json={'events':[event]},headers=headers).json()['acknowledged'],['b'*64])
        self.assertEqual(CentralStore(self.db).authenticate(token),device)
        other=TestClient(create_app(self.db,['testserver'],self.password),base_url='https://testserver')
        self.assertEqual(other.get('/api/agent/v1/status',headers=headers).json()['projects'][0]['project_id'],pid)
        self.assertEqual(other.post('/api/agent/v1/heartbeat',json={'device_id':'foreign'},headers=headers).status_code,400)
        self.assertEqual(other.post('/api/dashboard/import',json={},headers=headers).status_code,401)
        other.close()
    def test_security_and_disabled_features(self):
        self.assertEqual(self.client.get('/api/health',headers={'Host':'attacker.test','X-Forwarded-Host':'testserver'}).status_code,400)
        self.assertEqual(self.client.post('/api/login',headers={'Origin':'https://evil.test'},json={}).status_code,403)
        self.assertEqual(self.client.post('/api/login',headers={'Sec-Fetch-Site':'cross-site'},json={}).status_code,403)
        self.assertEqual(self.client.post('/api/agent/v1/projects',headers={'Content-Length':'2000001'},content='{}').status_code,413)
        self.assertEqual(self.client.post('/api/login',content='[]').status_code,400)
        self.login()
        for path in ('/api/scan','/api/analyze','/api/previews','/api/planner/instruction'):
            self.assertEqual(self.client.post(path,json={}).status_code,501)
        self.assertEqual(self.client.get('/api/access').status_code,403)
        self.assertEqual(self.client.get('/js/app.js').status_code,200)
        self.assertEqual(self.client.get('/api/agent/v1/execute').status_code,404)
        with patch.dict(os.environ,{'DATABASE_URL':'','POSTGRES_URL':''}):
            production=TestClient(create_app(hosts=['testserver'],password=self.password),base_url='https://testserver')
            response=production.get('/api/health')
            self.assertEqual(response.status_code,503)
            self.assertIn('POSTGRES_URL',response.json()['error'])
            production.close()
    def test_persistent_rate_limit(self):
        from tracker.cloud_http import CloudAuth
        first=CloudAuth(self.db); self.assertFalse(first.limited('test',1))
        self.assertTrue(CloudAuth(self.db).limited('test',1))
    def test_cloud_state_does_not_inspect_pc(self):
        from tracker import server
        self.login()
        with patch.object(server,'sync_dir',side_effect=AssertionError('local sync inspected')), \
             patch.object(server.analyzer,'find_claude',side_effect=AssertionError('local CLI inspected')), \
             patch.object(server.scanner,'build_snapshot',side_effect=AssertionError('PC scanned')):
            self.assertEqual(self.client.get('/api/state').status_code,200)
    def test_agent_requires_approved_origin_and_new_origin_credential(self):
        from agent.config import load
        root=Path(self.temp.name)/'approved'; (root/'.git').mkdir(parents=True)
        path=Path(self.temp.name)/'agent.json'
        config={'server':'https://project-dashboard.example.com','device_id':'paired','installation_id':'installation', 'workspaces':[str(root)]}
        path.write_text(json.dumps(config))
        with self.assertRaises(ValueError): load(path)
        config['approved_server']=config['server']; path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError,'Credential'): load(path)
        config['credential_server']=config['server']; path.write_text(json.dumps(config))
        self.assertEqual(load(path)[0]['server'],config['server'])
    def test_postgres_owned_dialect(self):
        self.assertIn('BIGSERIAL PRIMARY KEY',sql('CREATE TABLE items(id INTEGER PRIMARY KEY,data BLOB)'))
        self.assertIn('BYTEA',sql('CREATE TABLE images(data BLOB)'))
        self.assertEqual(sql('INSERT OR IGNORE INTO activities VALUES (?,?)'),'INSERT INTO activities VALUES (%s,%s) ON CONFLICT DO NOTHING')
        self.assertIn('GREATEST(timestamp,%s)',sql('UPDATE activities SET timestamp=MAX(timestamp,?) WHERE id=?'))
        with self.assertRaises(ValueError): PostgresDB('sqlite:///local.db')
        with self.assertRaises(ValueError): PostgresDB('postgresql://user:password@database.invalid/db?sslmode=disable')
    def test_postgres_cursor_without_description_and_neon_alias(self):
        from types import SimpleNamespace
        from tracker.postgres import row_factory, database, Connection
        self.assertEqual(row_factory(SimpleNamespace(description=None))(()),{})
        self.assertEqual(row_factory(SimpleNamespace(description=[SimpleNamespace(name='id')]))((7,))[0],7)
        with patch.dict(os.environ,{'DATABASE_URL':'','POSTGRES_URL':'neon-url'}), patch('tracker.postgres.PostgresDB') as constructor:
            database('unused',require_postgres=True)
            constructor.assert_called_once_with('neon-url')
        with patch.dict(os.environ,{'DATABASE_URL':'primary-url','POSTGRES_URL':'neon-url'}), patch('tracker.postgres.PostgresDB') as constructor:
            database('unused',require_postgres=True)
            constructor.assert_called_once_with('primary-url')
        from unittest.mock import Mock
        connection=Connection.__new__(Connection); connection.raw=Mock()
        connection.raw.execute.return_value.fetchone.return_value=None
        result=connection.execute('INSERT OR IGNORE INTO items(id) VALUES (?)',(1,))
        self.assertIsNone(result.lastrowid)
    def test_postgres_schema_comments_do_not_become_statements(self):
        from tracker.postgres import Connection
        from tracker.db import SCHEMA
        from unittest.mock import Mock
        connection=Connection.__new__(Connection); connection.raw=Mock(); connection.execute=Mock()
        connection.executescript(SCHEMA)
        statements=[call.args[0].strip() for call in connection.execute.call_args_list]
        self.assertTrue(statements)
        self.assertTrue(all(statement.startswith('CREATE ') for statement in statements),statements)

@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'Set TEST_DATABASE_URL to an isolated Neon test database')
class NeonPersistenceTests(unittest.TestCase):
    def test_authentication_survives_new_database_connections(self):
        url=os.environ['TEST_DATABASE_URL']; db=PostgresDB(url)
        store=CentralStore(db); identity='test-'+str(uuid.uuid4()); device=store.register(identity)
        self.assertEqual(CentralStore(PostgresDB(url)).authenticate(device['token']),identity)
        try:
            self.assertEqual(CentralStore(PostgresDB(url)).heartbeat(identity)['device_id'],identity)
        finally:
            with db.conn() as c: c.execute('DELETE FROM devices WHERE id=?',(identity,))

if __name__=='__main__': unittest.main()
