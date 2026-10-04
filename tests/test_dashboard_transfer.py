import copy
import tempfile
import unittest
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from tracker.db import DB
from tracker.central import CentralStore
from tracker import planner
from tracker.dashboard_transfer import export_dashboard, import_dashboard, saved_snapshots

class DashboardTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = DB(Path(self.temp.name) / 'source.sqlite')
        self.target = DB(Path(self.temp.name) / 'target.sqlite')
        self.old = 'PC|C:/work/example'
        self.new = 'central-example'
        self.snap = {'machine':'PC', 'scanned_at':'2026-10-04T12:00:00+00:00', 'projects':[
            {'key':'C:/work/example', 'name':'Example', 'kind':'folder', 'path':'C:/work/example',
             'git':{'remote':'https://github.com/test/example.git'}, 'recent_prompts':['PRIVATE CHAT BODY']},
            {'key':'session1', 'name':'PRIVATE CHAT BODY', 'kind':'codex-thread'}],
            'general':{'recent_prompts':['PRIVATE CHAT BODY']}}
        self.source.set_setting('cloud_password','PRIVATE CREDENTIAL')
        self.source.set_override(self.old, {'name':'Owner project name'})
        first = self.source.add_item(self.old, {'title':'Prerequisite'})
        self.source.add_item(self.old, {'title':'Dependent', 'depends_on':first})
        planner.add_manual(self.source, [{'id':self.old,'name':'Example'}], {'project_key':self.old,'title':'Today task'})
        self.source.save_analysis(self.old, {'phase':'Development','health':70}, {'model':'saved'})
        self.physical = self.source.create_physical({'name':'Drone', 'category':'Drone'})
        self.source.add_milestone(self.physical, 'Fly')

    def tearDown(self): self.temp.cleanup()

    def bundle(self): return export_dashboard(self.source, [self.snap], 'PC')

    def test_collision_remapping_and_retry_preserve_edits_and_devices(self):
        self.target.add_item('existing', {'title':'Production task'})
        store = CentralStore(self.target)
        device = store.register('Real-device')
        result = import_dashboard(self.target, self.bundle(), {self.old:self.new})
        self.assertEqual(result['imported']['items'], 3)
        self.assertEqual(store.authenticate(device['token']), 'Real-device')
        imported = self.target.items()[self.new]
        prerequisite = next(row for row in imported if row['title']=='Prerequisite')
        dependent = next(row for row in imported if row['title']=='Dependent')
        self.assertEqual(dependent['depends_on'], prerequisite['id'])
        self.target.update_item(prerequisite['id'], {'title':'Production edit'})
        with self.target.conn() as c:
            task = c.execute('SELECT * FROM plan_tasks').fetchone()
            self.assertEqual(task['project_key'], self.new)
            self.assertEqual(task['cid'], 'i'+str(task['item_id']))
            self.assertEqual(c.execute('SELECT project_id FROM milestones').fetchone()[0], self.target.physical()[0]['id'])
        retry = import_dashboard(self.target, self.bundle(), {self.old:self.new})
        self.assertTrue(all(count==0 for count in retry['imported'].values()))
        self.assertTrue(any(row['title']=='Production edit' for row in self.target.items()[self.new]))
        self.assertEqual(len(saved_snapshots(self.target)),1)

    def test_excludes_credentials_chats_and_unknown_tables(self):
        bundle = self.bundle()
        self.assertNotIn('PRIVATE', str(bundle))
        self.assertEqual(len(bundle['snapshots'][0]['projects']),1)
        bundle['tables']['settings'] = [{'key':'cloud_password','value':'bad'}]
        with self.assertRaises(ValueError): import_dashboard(self.target, bundle)
        self.assertEqual(self.target.items(), {})

    def test_failure_rolls_back_all_rows(self):
        bundle = self.bundle()
        bundle['tables']['milestones'][0]['project_id'] = 9999
        with self.assertRaises(ValueError): import_dashboard(self.target, bundle)
        self.assertEqual(self.target.items(), {})
        self.assertEqual(self.target.physical(), [])
        self.assertEqual(saved_snapshots(self.target), [])

    def test_owner_http_import_rejects_collector_and_exports_current_ids(self):
        from test_http_pipeline import server
        from tracker import security
        previous = server.db, server.central
        server.db, server.central = self.target, CentralStore(self.target)
        httpd = server.TrackerServer(('127.0.0.1',0), server.Handler)
        httpd.cloud = True; httpd.auth_required = True; httpd.expected_host = '127.0.0.1'
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        cookie = security.COOKIE + '=' + security.new_session()
        device = server.central.register('Authorized-collector')
        def request(path, body=None, headers=None):
            req = urllib.request.Request('http://127.0.0.1:' + str(httpd.server_port) + path,
                json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json', **(headers or {})})
            with urllib.request.urlopen(req) as response: return json.load(response)
        try:
            for headers in ({}, {'Authorization':'Bearer '+device['token']}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    request('/api/dashboard/import', self.bundle(), headers)
                self.assertEqual(error.exception.code,401); error.exception.close()
            request('/api/dashboard/import', self.bundle(), {'Cookie':cookie})
            state = request('/api/state', headers={'Cookie':cookie})
            self.assertEqual(state['projects'][0]['name'], 'Owner project name')
            self.assertFalse(state['projects'][0]['facts']['local'])
            exported = request('/api/dashboard/export', headers={'Cookie':cookie})
            self.assertEqual(len(exported['tables']['items']),3)
            self.assertEqual(exported['snapshots'][0]['projects'][0]['owner_key'],self.old)
            self.assertNotIn('PRIVATE', str(exported))
            self.assertEqual(server.central.authenticate(device['token']),device['device_id'])
            with patch('tracker.planner.llm_json', side_effect=AssertionError('Cloud regeneration must not call a local AI CLI')):
                regenerated = request('/api/planner/regenerate', {}, {'Cookie':cookie})
            self.assertIn('planner', regenerated)
            self.assertEqual(regenerated['planner']['plan']['source'],'rules')
        finally:
            httpd.shutdown(); httpd.server_close()
            server.db, server.central = previous

if __name__ == '__main__': unittest.main()
