import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tracker.connectors.workspace_suggestions import suggestions

class WorkspaceSuggestionTests(unittest.TestCase):
    def test_projects_containers_and_session_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            repo = home / 'Documents/Projects/example'
            (repo / '.git').mkdir(parents=True)
            (repo / 'src').mkdir()
            for name in ('.codex/sessions', '.copilot/chats', '.claude/projects'):
                (home / name / '.git').mkdir(parents=True)
            state = home / 'AppData/Roaming/Code/User/globalStorage/state.vscdb'
            state.parent.mkdir(parents=True)
            with sqlite3.connect(state) as db:
                db.execute('CREATE TABLE ItemTable (key TEXT, value TEXT)')
                db.execute('INSERT INTO ItemTable VALUES (?, ?)', ('history.recentlyOpenedPathsList', json.dumps({'entries': [{'folderUri': p.as_uri()} for p in (home, repo / 'src', home / '.copilot/chats')]})))
            db.close()
            with patch.dict('os.environ', {'OneDrive': '', 'OneDriveConsumer': ''}):
                rows = suggestions(home)
            paths = [row['path'] for row in rows]
            self.assertIn(str(repo), paths)
            self.assertIn(str(home / 'Documents/Projects'), paths)
            self.assertNotIn(str(home / 'Documents'), paths)
            self.assertNotIn(str(repo / 'src'), paths)
            self.assertNotIn(str(home), paths)
            self.assertFalse(any('.copilot' in p or '.codex' in p or '.claude' in p for p in paths))
            self.assertEqual(len(paths), len(set(p.lower() for p in paths)))
            self.assertEqual(next(r['source'] for r in rows if r['path'] == str(repo)), 'Detected Git repository')

if __name__ == '__main__': unittest.main()
