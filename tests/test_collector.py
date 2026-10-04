import json
import tempfile
import unittest
from pathlib import Path
from tracker.connectors.local_workspace import discover
from tracker.connectors.ai_metadata import collect_sessions
from tracker.central import now

class CollectorTests(unittest.TestCase):
    def test_excludes_files_and_does_not_send_bodies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'package.json').write_text('{}')
            (root/'main.py').write_text('# TODO verify\npassword="do-not-transmit"')
            (root/'.env').write_text('TOKEN=do-not-transmit')
            (root/'node_modules').mkdir()
            (root/'node_modules'/'hidden.py').write_text('# TODO hidden')
            projects,warnings=discover([tmp])
            self.assertFalse(warnings)
            self.assertEqual(len(projects),1)
            self.assertEqual(projects[0]['todo_count'],1)
            self.assertEqual(projects[0]['file_count'],2)
            self.assertNotIn('do-not-transmit',json.dumps(projects))

    def test_session_mapping_without_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            session=root/'session.jsonl'
            session.write_text(json.dumps({'type':'session_meta','timestamp':now(),'payload':{'cwd':'C:/work/app','id':'session-id','base_instructions':'SECRET'}})+'\n'+json.dumps({'type':'message','timestamp':now(),'payload':{'prompt':'SECRET'}}))
            projects=[{'path':'C:/work/app'}]
            reports=collect_sessions(projects,{'codex':tmp,'claude':str(root/'missing')})
            self.assertEqual(len(projects[0]['ai_sessions']),1)
            self.assertNotIn('SECRET',json.dumps(projects))
            self.assertEqual(next(r for r in reports if r['name']=='claude')['status'],'unavailable')

if __name__=='__main__': unittest.main()
