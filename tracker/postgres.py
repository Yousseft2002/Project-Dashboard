"""PostgreSQL persistence for the existing parameterized store API.

The compatibility layer translates only our owned SQLite dialect statements;
request input is always passed separately as driver parameters.
"""
import re
from urllib.parse import urlsplit, parse_qs
from .db import DB, SCHEMA, OVERRIDE_COLUMNS, ITEM_COLUMNS

SERIAL_TABLES={'physical_projects','physical_updates','milestones','analyses','items',
               'directives','plan_tasks','planner_events','ingestion_events'}

class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)

def row_factory(cursor):
    names=[col.name for col in (cursor.description or ())]
    return lambda values: Row(zip(names,values))

def sql(statement):
    statement=re.sub(r'--[^\n]*','',statement).strip().rstrip(';')
    statement=re.sub(r'\bid INTEGER PRIMARY KEY\b','id BIGSERIAL PRIMARY KEY',statement,flags=re.I)
    statement=re.sub(r'\bBLOB\b','BYTEA',statement,flags=re.I)
    statement=re.sub(r'\bMAX\((ai_sessions\.timestamp|timestamp),','GREATEST(\\1,',statement)
    if re.match(r'INSERT OR IGNORE\b',statement,re.I):
        statement=re.sub(r'INSERT OR IGNORE','INSERT',statement,flags=re.I)+' ON CONFLICT DO NOTHING'
    statement=re.sub(r'UPDATE OR IGNORE','UPDATE',statement,flags=re.I)
    statement=re.sub(r'(ALTER TABLE \w+ ADD COLUMN) (?!IF NOT EXISTS)',r'\1 IF NOT EXISTS ',statement,flags=re.I)
    # Placeholders never occur in owned SQL string literals.
    return statement.replace('?','%s')

class Result:
    def __init__(self,cursor=None,rows=None,lastrowid=None):
        self.cursor=cursor; self.rows=rows; self.lastrowid=lastrowid
        self.rowcount=cursor.rowcount if cursor else 0
    def fetchall(self): return self.cursor.fetchall() if self.rows is None else self.rows
    def fetchone(self):
        if self.rows is None: return self.cursor.fetchone()
        return self.rows.pop(0) if self.rows else None
    def __iter__(self): return iter(self.fetchall())

class Connection:
    def __init__(self,url):
        import psycopg
        self.raw=psycopg.connect(url,row_factory=row_factory,connect_timeout=10)
    def __enter__(self): return self
    def __exit__(self,kind,value,tb):
        try: self.raw.rollback() if kind else self.raw.commit()
        finally: self.raw.close()
    def execute(self,statement,parameters=()):
        pragma=re.fullmatch(r'PRAGMA table_info\((\w+)\)',statement.strip(),re.I)
        if pragma:
            cur=self.raw.execute("SELECT ordinal_position-1 AS cid,column_name AS name,data_type AS type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position",(pragma[1],))
            return Result(cur)
        if statement.strip().lower()=='pragma quick_check': return Result(rows=[Row(result='ok')])
        ignore=bool(re.match(r'UPDATE OR IGNORE\b',statement,re.I))
        if ignore: self.raw.execute('SAVEPOINT compatible_update')
        query=sql(statement)
        match=re.match(r'INSERT INTO (\w+)\b',query,re.I)
        returning=bool(match and match[1] in SERIAL_TABLES and 'RETURNING' not in query.upper())
        if returning: query+=' RETURNING id'
        try:
            cursor=self.raw.execute(query,parameters)
        except Exception as error:
            import psycopg
            if ignore and isinstance(error,psycopg.errors.UniqueViolation):
                self.raw.execute('ROLLBACK TO SAVEPOINT compatible_update')
                self.raw.execute('RELEASE SAVEPOINT compatible_update')
                return Result(rows=[])
            raise
        if ignore: self.raw.execute('RELEASE SAVEPOINT compatible_update')
        returned=cursor.fetchone() if returning else None
        inserted=returned[0] if returned is not None else None
        return Result(cursor,lastrowid=inserted)
    def executescript(self,script):
        self.raw.execute('SELECT pg_advisory_xact_lock(714236001)')
        # Owned schemas contain semicolons inside line comments. Strip those
        # comments before splitting so their prose never becomes executable SQL.
        for statement in re.sub(r'--[^\n]*','',script).split(';'):
            if statement.strip(): self.execute(statement)

class PostgresDB(DB):
    backend='postgresql'
    def __init__(self,url):
        parsed=urlsplit(url)
        if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname:
            raise ValueError('DATABASE_URL must be a PostgreSQL connection URL')
        if parse_qs(parsed.query).get('sslmode',[''])[0] not in ('require','verify-ca','verify-full'):
            raise ValueError('DATABASE_URL must require TLS (sslmode=require or stricter)')
        self.url=url
        with self.conn() as c:
            # Transaction-scoped migration lock works with Neon's pooled URL.
            c.raw.execute('SELECT pg_advisory_xact_lock(714236001)')
            c.executescript(SCHEMA)
            for table,columns in (('digital_overrides',OVERRIDE_COLUMNS),('items',ITEM_COLUMNS)):
                for name,kind in columns.items(): c.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}')
    def conn(self): return Connection(self.url)

def database(path,require_postgres=False):
    import os
    url=os.environ.get('DATABASE_URL','') or os.environ.get('POSTGRES_URL','')
    if url: return PostgresDB(url)
    if require_postgres: raise ValueError('DATABASE_URL or POSTGRES_URL is required; Vercel cannot persist to SQLite')
    return DB(path)
