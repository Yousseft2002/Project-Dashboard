import json
import tempfile
import unittest
from pathlib import Path
from tracker.db import DB
from tracker.central import CentralStore, now, repository

class CentralTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DB(Path(self.tmp.name)/'tracker.db')
        self.store = CentralStore(self.db)
        self.a = self.store.register('Laptop')
        self.b = self.store.register('Desktop')

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, remote='git@github.com:Owner/Project.git', path='C:\\Projects\\test'):
        return {'name':'test', 'path':path, 'repository':remote, 'last_activity':now(), 'commits':[{'sha':'a'*40, 'timestamp':now()}]}

    def test_two_devices_retry_and_restart(self):
        a = self.project()
        b = self.project('https://github.com/owner/project', 'D:\\work\\test')
        for device,p in [('Laptop',a), ('Desktop',b), ('Laptop',a)]:
            self.store.ingest(device, {'projects':[p]})
        snapshot = CentralStore(DB(self.db.path)).snapshot()
        self.assertEqual(len(snapshot['projects']),1)
        self.assertEqual(len(snapshot['projects'][0]['observations']),2)
        self.assertEqual(sum(e['event_type']=='commit' for e in snapshot['activity']),1)
        self.store.ingest('Laptop', {'projects':[]})
        self.assertEqual(len(self.store.snapshot()['projects']),1)

    def test_auth_rotation_and_revoke(self):
        self.assertEqual(self.store.authenticate(self.a['token']), 'Laptop')
        self.assertIsNone(self.store.authenticate('bad'))
        self.store.register('Laptop')
        self.assertIsNone(self.store.authenticate(self.a['token']))
        with self.db.conn() as c:
            self.assertNotIn(self.b['token'], str(c.execute('SELECT * FROM devices').fetchall()))

    def test_validate_atomically_and_filter_contents(self):
        p = self.project()
        p['raw_prompt']='a secret'
        p['env']={'TOKEN':'secret'}
        self.store.ingest('Laptop', {'projects':[p]})
        serialized=json.dumps(self.store.snapshot())
        self.assertNotIn('a secret',serialized)
        self.assertNotIn('TOKEN',serialized)
        with self.assertRaises(ValueError):
            self.store.ingest('Desktop', {'projects':[self.project(path='D:/new'), {'name':'invalid'}]})
        self.assertEqual(len(self.store.snapshot()['projects'][0]['observations']),1)

    def test_identity_upgrade_preserves_task(self):
        p=self.project(remote='')
        self.store.ingest('Laptop', {'projects':[p]})
        pid=self.store.snapshot()['projects'][0]['id']
        self.db.add_item(pid, {'title':'Human task'})
        p['repository']='https://github.com/owner/project.git'
        self.store.ingest('Laptop', {'projects':[p]})
        self.assertEqual(self.store.snapshot()['projects'][0]['id'],pid)
        self.assertEqual(self.db.items()[pid][0]['title'],'Human task')

    def test_credentials_removed_from_remote(self):
        self.assertEqual(repository('https://user:password@github.com/OWNER/Project.git?token=secret'), 'github.com/owner/project')
        self.assertEqual(repository('ssh://git@github.com/owner/project.git'), 'github.com/owner/project')

if __name__=='__main__':
    unittest.main()
