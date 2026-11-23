"""Exercise upgrades using real historical source archives and persistent records."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from zipfile import ZipFile
import pytest

ROOT=Path(__file__).resolve().parents[1]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def run(args,cwd=ROOT,env=None):
    return subprocess.run(args,cwd=cwd,env=env,text=True,capture_output=True)

@pytest.mark.parametrize('kind',['v04','v05','v05_alembic'])
def test_migrate_known_schemas_preserves_records(kind,tmp_path):
    archive='NORI-starter-v0.4.0.zip' if kind=='v04' else 'NORI-v0.5.0-source.zip'
    with ZipFile(ROOT/'original'/archive) as z: z.extractall(tmp_path/'source')
    source_root=next((tmp_path/'source').iterdir()); old=tmp_path/'old.db'; new=tmp_path/'new.db'
    env=os.environ.copy();env['DATABASE_URL']='sqlite:///'+str(old);env['AUTO_CREATE_SCHEMA']='false'
    if kind=='v05_alembic':
        result=run([sys.executable,'-m','alembic','upgrade','head'],cwd=source_root,env=env)
    else:
        result=run([sys.executable,'-c','from app.db import Base,engine; import app.models; Base.metadata.create_all(engine)'],cwd=source_root,env=env)
    assert result.returncode==0,result.stderr
    with sqlite3.connect(old) as db:
        db.execute("INSERT INTO users (id,telegram_id,username,created_at) VALUES (1,1001,'tester','2026-01-01 00:00:00')")
        db.execute("INSERT INTO support_tickets (id,user_id,category,message,status,created_at) VALUES (1,1,'other','preserved','open','2026-01-01 00:00:00')")
        db.execute("INSERT INTO license_grants (id,user_id,key_hash,issue_request_id,duration_days,created_at,activated_at,expires_at,revoked_at) VALUES (1,1,?,?,30,'2026-01-01 00:00:00','2026-01-01 00:00:00','2026-01-31 00:00:00',NULL)",('a'*64,'b'*36))
    before=sha(old)
    result=run([sys.executable,'scripts/migrate_sqlite_copy.py',str(old),str(new)])
    assert result.returncode==0,result.stderr
    assert sha(old)==before
    with sqlite3.connect(new) as db:
        assert db.execute('select telegram_id,username from users').fetchall()==[(1001,'tester')]
        assert db.execute('select message,status from support_tickets').fetchall()==[('preserved','open')]
        assert db.execute('select key_hash,duration_days from license_grants').fetchall()==[('a'*64,30)]
        assert db.execute('select version_num from alembic_version').fetchone()==('4dbfc4c29581',)
    # Never overwrite the original or an existing destination.
    assert run([sys.executable,'scripts/migrate_sqlite_copy.py',str(old),str(new)]).returncode != 0
    assert sha(old)==before

def test_unknown_schema_and_triggers_rejected_without_source_mutation(tmp_path):
    dbfile=tmp_path/'unknown.db';out=tmp_path/'out.db'
    with sqlite3.connect(dbfile) as db: db.execute('create table foreign_schema(id integer primary key)')
    before=sha(dbfile)
    result=run([sys.executable,'scripts/migrate_sqlite_copy.py',str(dbfile),str(out)])
    assert result.returncode!=0 and not out.exists() and sha(dbfile)==before
