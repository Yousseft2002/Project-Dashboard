import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from agent.queue import Queue
from agent.sync import flush
from agent.security import safe_path, workspace, text
from agent.adapters.git import snapshot
from agent.api.client import AgentClient
from collector import CollectorError
from tracker.central import CentralStore, now
from tracker.db import DB
from tracker.agent_api import event_batch, dispatch

class AgentTests(unittest.TestCase):
    def setUp(self):
        fixture_root=Path(__file__).resolve().parents[1]/'data'
        fixture_root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=fixture_root); self.root=Path(self.temp.name).resolve()
        self.queue=Queue(self.root/'queue.sqlite')
        self.db=DB(self.root/'server.sqlite'); self.store=CentralStore(self.db)
        self.device=self.store.register('existing-paired-device')
        self.project={'name':'Example','path':'C:/work/example','repository':'https://github.com/test/example.git','commits':[{'sha':'a'*40,'timestamp':now(),'message':'Useful commit'}]}
        self.event={'event_id':'b'*64,'device_id':self.device['device_id'],'project_id':'local-project','source':'git','event_type':'commit','timestamp':now(),'summary':'Useful commit','metadata':{'sha':'a'*40}}
        self.config={'device_id':self.device['device_id']}
    def tearDown(self): self.temp.cleanup()

    def client(self, lose_ack=False):
        store=self.store; device=self.device['device_id']
        class Client:
            lost=False
            def request(inner,path,body):
                result=store.ingest(device,body) if path.endswith('/projects') else event_batch(store,device,body)
                if lose_ack and path.endswith('/events/batch') and not inner.lost:
                    inner.lost=True; raise CollectorError('Connection lost after server receipt')
                return result
        return Client()

    def test_offline_restart_lost_receipt_and_replay(self):
        self.queue.put('local-project',self.project,[self.event])
        queue=Queue(self.root/'queue.sqlite')
        self.assertEqual(queue.pending(),1)
        client=self.client(True)
        with self.assertRaises(CollectorError): flush(client,self.config,queue)
        self.assertEqual(queue.pending(),1)
        flush(client,self.config,queue)
        self.assertEqual(queue.pending(),0)
        queue.put('local-project',self.project,[self.event])
        self.assertEqual(queue.pending(),0)
        with self.db.conn() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM agent_events').fetchone()[0],1)
        self.assertEqual(sum(e['event_type']=='commit' for e in self.store.snapshot()['activity']),1)

    def test_windows_queue_ciphertext(self):
        self.queue.put('local-project',self.project,[self.event])
        if os.name=='nt':
            with closing(self.queue.connect()) as c:
                value=c.execute('SELECT data FROM events').fetchone()[0]
                self.assertTrue(value.startswith('dpapi:'))
                self.assertNotIn('Useful commit',value)

    def test_service_once_collects_and_uploads(self):
        from agent import service
        config=dict(self.config,installation_id='existing-installation',device_name='YT-Laptop',
                    server='https://project-dashboard-0d02.onrender.com',workspaces=[self.project['path']],reconcile_seconds=900)
        client=self.client()
        client.health=lambda: {'agent_api_version':1}
        client.register_agent=lambda config: None
        client.heartbeat_agent=lambda config,count: {}
        def collect(config,queue): queue.put('local-project',self.project,[self.event])
        with patch.object(service,'load',return_value=(config,self.root/'config.json')), \
             patch.object(service,'credential',return_value='protected-token'), \
             patch.object(service,'AgentClient',return_value=client), patch.object(service,'collect',side_effect=collect):
            service.run(self.root/'config.json',once=True)
        diagnostics=json.loads((self.root/'data/agent/diagnostics.json').read_text())
        self.assertTrue(diagnostics['connected'])
        self.assertEqual(diagnostics['pending'],0)
        self.assertIn('last_sync',diagnostics)

    def test_git_external_config_include_rejected(self):
        repo=self.root/'included'; repo.mkdir()
        subprocess.run(['git','-C',str(repo),'init'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'config','include.path',str(self.root/'outside')],check=True,capture_output=True)
        with self.assertRaisesRegex(ValueError,'includes'): snapshot(repo,self.device['device_id'])

    def test_repair_retains_queue_and_removed_allowlist_cannot_upload(self):
        self.queue.put('local-project',self.project,[self.event])
        self.queue.rebind('replacement-device')
        self.assertEqual(self.queue.pending(),1)
        rows=self.queue.projects(); self.queue.mapped(rows,['project-example'])
        self.assertEqual(self.queue.events()[0]['device_id'],'replacement-device')
        self.queue.allowlist([self.root/'different-repository'])
        self.assertEqual(self.queue.projects(True),[])
        self.assertEqual(self.queue.events(),[])
        self.assertEqual(self.queue.pending(),1)

    def test_malicious_ack_cannot_discard_queue(self):
        self.queue.put('local-project',self.project,[self.event])
        class Bad:
            def request(inner,path,body):
                if path.endswith('/projects'): return {'database_write':True,'device_id':self.config['device_id'],'project_ids':['project-example']}
                return {'ok':True,'device_id':self.config['device_id'],'database_write':True,'acknowledged':['other-event']}
        with self.assertRaises(CollectorError): flush(Bad(),self.config,self.queue)
        self.assertEqual(self.queue.pending(),1)

    def test_snapshot_changed_during_request_stays_dirty(self):
        self.queue.put('local-project',self.project,[]); rows=self.queue.projects()
        self.queue.put('local-project',dict(self.project,branch='new-branch'),[])
        self.queue.mapped(rows,['project-example'])
        self.assertEqual(len(self.queue.projects()),1)

    def test_event_validation_and_atomic_rollback(self):
        pid=self.store.ingest(self.device['device_id'],{'projects':[self.project]})['project_ids'][0]
        event=dict(self.event,project_id=pid)
        cases=[dict(event,device_id='other'),dict(event,source='shell'),dict(event,timestamp='2100-01-01T00:00:00Z'),dict(event,summary='x'*301),dict(event,metadata={'command':'powershell evil'}),dict(event,event_id='../../evil')]
        for bad in cases:
            with self.assertRaises(ValueError): event_batch(self.store,self.device['device_id'],{'events':[bad]})
        with self.assertRaises(ValueError): event_batch(self.store,self.device['device_id'],{'events':[event,dict(event,event_id='c'*64,project_id='unowned-project')]})
        with self.db.conn() as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM agent_events').fetchone()[0],0)

    def test_device_uuid_stays_stable_and_no_hardware_identity(self):
        from agent.identity import identity
        config={'installation_id':'existing-installation','device_id':self.device['device_id']}
        first=identity(config,self.root/'config.json')
        self.assertEqual(first,identity(config,self.root/'config.json'))
        self.assertEqual(str(uuid.UUID(first)),first)
        self.assertEqual(config['device_id'],self.device['device_id'])

    def test_security_paths_exclusions_and_redaction(self):
        repo=self.root/'repository'; (repo/'.git').mkdir(parents=True)
        self.assertEqual(workspace(repo),repo)
        for name in ('../outside.py','.env','.env.production','.ssh/id_rsa','secret-api-key.txt','node_modules/index.js'):
            self.assertIsNone(safe_path(repo,name))
        self.assertNotIn('actual-token',text('password=actual-token\nforged-log'))
        self.assertNotIn('\n',text('injected\nlog'))
        outside=self.root/'outside'; outside.mkdir()
        try: (repo/'linked').symlink_to(outside,target_is_directory=True)
        except OSError: pass
        else: self.assertIsNone(safe_path(repo,'linked/private.py'))

    def test_git_adapter_reads_no_source_bodies_and_filters_secrets(self):
        repo=self.root/'code'; repo.mkdir()
        def git(*args): subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
        git('init'); (repo/'source.py').write_text('PRIVATE SOURCE BODY'); (repo/'.env').write_text('PRIVATE SECRET')
        git('add','.'); git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','Initial useful commit')
        (repo/'.env').write_text('NEW SECRET'); (repo/'source.py').write_text('UPDATED SOURCE')
        with patch.object(Path,'read_text',side_effect=AssertionError('Source reads prohibited')):
            pid,project,events=snapshot(repo,self.device['device_id'])
        self.assertEqual(project['changed_files'],1)
        self.assertEqual(project['file_count'],1)
        self.assertNotIn('PRIVATE',json.dumps([project,events]))
        self.assertEqual(events[0]['summary'],'Initial useful commit')

    def test_versioned_http_preserves_pairing_and_has_no_command_endpoint(self):
        from test_http_pipeline import server
        previous=server.db,server.central; server.db,server.central=self.db,self.store
        httpd=server.TrackerServer(('127.0.0.1',0),server.Handler)
        httpd.cloud=True; httpd.auth_required=True; httpd.expected_host='127.0.0.1'
        threading.Thread(target=httpd.serve_forever,daemon=True).start()
        client=AgentClient('http://127.0.0.1:'+str(httpd.server_port),self.device['token'])
        try:
            self.assertEqual(client.health()['agent_api_version'],1)
            config=dict(self.config,device_name='YT-Laptop',installation_id='same-installation',agent_id=str(uuid.uuid4()))
            client.register_agent(config); client.heartbeat_agent(config,1)
            self.queue.put('local-project',self.project,[self.event]); flush(client,config,self.queue)
            self.assertEqual(self.queue.pending(),0)
            with self.assertRaises(CollectorError): client.request('/api/agent/v1/execute',{'command':'evil'})
            with self.assertRaises(CollectorError): client.request('/api/dashboard/import',{})
            self.assertEqual(self.store.authenticate(self.device['token']),self.device['device_id'])
        finally:
            httpd.shutdown(); httpd.server_close(); server.db,server.central=previous

if __name__=='__main__': unittest.main()
