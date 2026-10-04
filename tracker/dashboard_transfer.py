"""Owner-authorized transfer of saved dashboard state, separate from collectors."""
import hashlib
import base64
import json
from pathlib import Path

TABLES = ('digital_overrides', 'analyses', 'items', 'directives', 'plan_days',
          'plan_tasks', 'planner_events', 'task_bias', 'physical_projects',
          'physical_updates', 'milestones')
RAW_FIELDS = ('key', 'name', 'path', 'kind', 'git', 'files', 'stack', 'docs',
              'readme', 'checklist', 'folder_created', 'ai_tools', 'ai_last',
              'ai_first', 'activity', 'last_activity', 'created', 'owner_key')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS dashboard_import_snapshots (
 source TEXT NOT NULL, machine TEXT NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(source,machine));
CREATE TABLE IF NOT EXISTS dashboard_import_rows (
 source TEXT NOT NULL, table_name TEXT NOT NULL, old_key TEXT NOT NULL,
 new_key TEXT NOT NULL, PRIMARY KEY(source,table_name,old_key));
CREATE TABLE IF NOT EXISTS dashboard_import_previews (
 project_key TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, data BLOB NOT NULL);
'''

def initialize(db):
    with db.conn() as c:
        c.executescript(SCHEMA)

def saved_snapshots(db):
    initialize(db)
    with db.conn() as c:
        return [json.loads(row['data']) for row in c.execute('SELECT data FROM dashboard_import_snapshots')]

def export_dashboard(db, snapshots, machine, preview_directory=None):
    """No settings, credential records, source files, or AI chat bodies."""
    clean = []
    for snap in snapshots:
        clean.append({
            'version': snap.get('version', 1), 'machine': snap['machine'],
            'scanned_at': snap['scanned_at'], 'totals': snap.get('totals', {}),
            'general': {'ai_tools': snap.get('general', {}).get('ai_tools', {})},
            'projects': [{key: p[key] for key in RAW_FIELDS if key in p} for p in snap['projects'] if p.get('kind') == 'folder'],
        })
    project_keys = {p.get('owner_key') or snap['machine'] + '|' + p['key'] for snap in clean for p in snap['projects']}
    with db.conn() as c:
        rows = {table: [dict(row) for row in c.execute('SELECT * FROM ' + table)] for table in TABLES}
    for table in ('analyses', 'digital_overrides', 'items'):
        field = 'key' if table != 'items' else 'project_key'
        rows[table] = [row for row in rows[table] if row[field] in project_keys]
    source = hashlib.sha256(str(machine).encode()).hexdigest()[:24]
    images = {}
    if preview_directory:
        for key in project_keys:
            path = Path(preview_directory) / (hashlib.sha1(key.encode()).hexdigest()[:16] + '.png')
            if path.is_file() and path.stat().st_size <= 2_000_000:
                images[key] = base64.b64encode(path.read_bytes()).decode()
    initialize(db)
    with db.conn() as c:
        for row in c.execute('SELECT project_key,data FROM dashboard_import_previews'):
            images.setdefault(row['project_key'], base64.b64encode(row['data']).decode())
    return {'format': 'project-dashboard-owner-export', 'version': 1,
            'source': source, 'snapshots': clean, 'tables': rows, 'previews': images}

def validate(bundle, db):
    if not isinstance(bundle, dict) or bundle.get('format') != 'project-dashboard-owner-export' or bundle.get('version') != 1:
        raise ValueError('Choose a Project Dashboard owner export (version 1).')
    source = bundle.get('source')
    if not isinstance(source, str) or len(source) != 24 or any(ch not in '0123456789abcdef' for ch in source):
        raise ValueError('Invalid export source.')
    snaps, tables = bundle.get('snapshots'), bundle.get('tables')
    if not isinstance(snaps, list) or len(snaps) > 30 or not isinstance(tables, dict) or set(tables) - set(TABLES):
        raise ValueError('Invalid export contents.')
    images = bundle.get('previews', {})
    if not isinstance(images, dict) or len(images) > 50:
        raise ValueError('Invalid preview images.')
    for key, encoded in images.items():
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError): raise ValueError('Invalid preview image.')
        if not isinstance(key, str) or len(content) > 2_000_000 or not content.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Preview must be a PNG under 2 MB.')
    for snap in snaps:
        if not isinstance(snap, dict) or not isinstance(snap.get('machine'), str) or not isinstance(snap.get('scanned_at'), str) or not isinstance(snap.get('projects'), list) or len(snap['projects']) > 1000:
            raise ValueError('Invalid saved project snapshot.')
        for p in snap['projects']:
            if not isinstance(p, dict) or set(p) - set(RAW_FIELDS) or not isinstance(p.get('key'), str) or not isinstance(p.get('name'), str):
                raise ValueError('Invalid saved project metadata.')
            if p.get('kind') != 'folder' or p.get('git') is not None and not isinstance(p['git'], dict):
                raise ValueError('Dashboard transfer accepts real project folders only.')
            if p.get('owner_key') is not None and not isinstance(p['owner_key'], str):
                raise ValueError('Invalid saved project identifier.')
        if set(snap) - {'version', 'machine', 'scanned_at', 'totals', 'general', 'projects'}:
            raise ValueError('Unexpected snapshot field.')
        if not isinstance(snap.get('general', {}), dict) or set(snap.get('general', {})) - {'ai_tools'}:
            raise ValueError('AI conversation content is not part of dashboard transfer.')
    with db.conn() as c:
        for table, rows in tables.items():
            columns = {r['name'] for r in c.execute('PRAGMA table_info(' + table + ')')}
            if not isinstance(rows, list) or len(rows) > 10000:
                raise ValueError('Too many saved dashboard rows.')
            keys = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) - columns or any(isinstance(v, (list, dict)) for v in row.values()):
                    raise ValueError('Invalid ' + table + ' row.')
                pk = 'id' if 'id' in columns else 'key' if 'key' in columns else 'day' if 'day' in columns else 'task_key'
                if pk not in row or str(row[pk]) in keys:
                    raise ValueError('Missing or duplicate saved row ID.')
                keys.add(str(row[pk]))
    return source

def import_dashboard(db, bundle, project_map=None):
    """Merge atomically, remap IDs, and preserve existing owner edits on retries."""
    source = validate(bundle, db)
    initialize(db)
    project_map = project_map or {}
    counts = {}
    with db.conn() as c:
        maps = {table: {r['old_key']: r['new_key'] for r in c.execute(
            'SELECT old_key,new_key FROM dashboard_import_rows WHERE source=? AND table_name=?', (source, table))} for table in TABLES}
        def reference(table, old):
            if old is None: return None
            value = maps[table].get(str(old))
            return int(value) if value is not None else None
        def cid(value):
            if isinstance(value, str) and value[:1] == 'i' and value[1:].isdigit():
                target = reference('items', int(value[1:]))
                return 'i' + str(target) if target is not None else value
            return value
        def nested(value):
            if isinstance(value, list): return [nested(v) for v in value]
            if not isinstance(value, dict): return value
            result = dict(value)
            for key in ('pid', 'project_key'):
                if key in result: result[key] = project_map.get(result[key], result[key])
            if 'cid' in result: result['cid'] = cid(result['cid'])
            if 'item_id' in result: result['item_id'] = reference('items', result['item_id'])
            return result
        order = ('physical_projects', 'items', 'analyses', 'digital_overrides', 'directives',
                 'plan_days', 'plan_tasks', 'planner_events', 'task_bias', 'physical_updates', 'milestones')
        inserted_items = []
        for table in order:
            rows = bundle['tables'].get(table, [])
            counts[table] = 0
            for original in rows:
                row = dict(original)
                pk = 'id' if 'id' in row else 'key' if 'key' in row else 'day' if 'day' in row else 'task_key'
                old_key = str(row[pk])
                if old_key in maps[table]: continue
                if 'project_key' in row: row['project_key'] = project_map.get(row['project_key'], row['project_key'])
                if table in ('analyses', 'digital_overrides'): row['key'] = project_map.get(row['key'], row['key'])
                if table == 'digital_overrides' and row.get('merge_into'): row['merge_into'] = project_map.get(row['merge_into'], row['merge_into'])
                if table == 'items': row['depends_on'] = None
                if table in ('physical_updates', 'milestones'):
                    row['project_id'] = reference('physical_projects', row['project_id'])
                    if row['project_id'] is None: raise ValueError('Missing physical project reference.')
                if table == 'plan_tasks':
                    row['item_id'] = reference('items', row.get('item_id'))
                    row['cid'] = cid(row.get('cid', ''))
                if table == 'planner_events': row['task_id'] = reference('plan_tasks', row.get('task_id'))
                if table == 'directives': row['track_item_ids'] = json.dumps([reference('items', i) for i in json.loads(row.get('track_item_ids', '[]')) if reference('items', i) is not None])
                if table == 'plan_days':
                    row['candidates'] = json.dumps(nested(json.loads(row.get('candidates', '[]'))))
                    directives = json.loads(row.get('directives', '[]'))
                    row['directives'] = json.dumps([{**d, 'id': reference('directives', d.get('id'))} if isinstance(d, dict) else reference('directives', d) for d in directives])
                if table == 'task_bias': row['task_key'] = cid(row['task_key'])
                if pk == 'id': del row['id']
                columns = list(row)
                # Natural keys already in production retain their owner's edits.
                if pk != 'id':
                    existing = c.execute(f'SELECT {pk} FROM {table} WHERE {pk}=?', (row[pk],)).fetchone()
                    if existing and table == 'plan_days' and not c.execute('SELECT 1 FROM plan_tasks WHERE day=? LIMIT 1', (row['day'],)).fetchone():
                        updates = [key for key in columns if key != pk]
                        c.execute('UPDATE plan_days SET ' + ','.join(key + '=?' for key in updates) + ' WHERE day=?', [row[key] for key in updates] + [row['day']])
                    if existing:
                        new_key = str(existing[pk])
                    else:
                        c.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', [row[k] for k in columns])
                        new_key = str(row[pk]); counts[table] += 1
                else:
                    cursor = c.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})', [row[k] for k in columns])
                    new_key = str(cursor.lastrowid); counts[table] += 1
                maps[table][old_key] = new_key
                c.execute('INSERT INTO dashboard_import_rows VALUES (?,?,?,?)', (source, table, old_key, new_key))
                if table == 'items': inserted_items.append((new_key, original.get('depends_on')))
        for item, dependency in inserted_items:
            c.execute('UPDATE items SET depends_on=? WHERE id=?', (reference('items', dependency), item))
        for snap in bundle['snapshots']:
            c.execute('INSERT INTO dashboard_import_snapshots VALUES (?,?,?) ON CONFLICT(source,machine) DO UPDATE SET data=excluded.data', (source, snap['machine'], json.dumps(snap)))
        for old_key, encoded in bundle.get('previews', {}).items():
            key = project_map.get(old_key, old_key)
            name = hashlib.sha1(key.encode()).hexdigest()[:16] + '.png'
            c.execute('INSERT INTO dashboard_import_previews VALUES (?,?,?) ON CONFLICT(project_key) DO NOTHING', (key, name, base64.b64decode(encoded)))
    return {'ok': True, 'imported': counts, 'snapshots': len(bundle['snapshots']), 'source': source}
