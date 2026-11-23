"""Copy and migrate only a known v0.4/v0.5 SQLite schema; never edit the source.
Stop writers first. See docs/MIGRATION.md. Unknown or modified schemas fail closed.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from sqlite_schema import schema

ROOT=Path(__file__).resolve().parents[1]
BASELINE_REV='abf453d198fe'
V05_REV='d296277344ed'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path);ap.add_argument('destination',type=Path)
    args=ap.parse_args(); src=args.source.resolve(); dst=args.destination.resolve()
    if not src.is_file(): raise ValueError('Source database not found')
    if src==dst or dst.exists(): raise ValueError('Destination must be a new file distinct from source')
    if '?' in str(dst) or '#' in str(dst): raise ValueError('Destination path must not contain ? or #')
    if not dst.parent.is_dir(): raise ValueError('Destination directory does not exist')
    baselines={v:json.loads((ROOT/'scripts'/f'{v}_sqlite_schema.json').read_text()) for v in ('v04','v05','v05_alembic')}
    created=False
    try:
        # sqlite backup API reads a consistent database, including committed WAL data.
        with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as old:
            # O_EXCL prevents overwriting an existing destination.
            fd=os.open(dst,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);created=True
            with sqlite3.connect(dst) as copy: old.backup(copy)
        with sqlite3.connect(dst) as copy:
            if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('SQLite integrity check failed')
            if copy.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Foreign key integrity check failed')
            actual=schema(copy)
            version=next((v for v,baseline in baselines.items() if baseline==actual),None)
            if not version: raise ValueError('Schema does not exactly match known v0.4 or v0.5; manual migration required')
            has_alembic=copy.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone()
            revisions=[r[0] for r in copy.execute('SELECT version_num FROM alembic_version')] if has_alembic else []
            if revisions and not (version in ('v05','v05_alembic') and revisions==[V05_REV]): raise ValueError('Unexpected Alembic revision; manual migration required')
            if has_alembic and not revisions: raise ValueError('Empty Alembic version table; manual migration required')
            counts={name:copy.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in actual}
        env=os.environ.copy();env['DATABASE_URL']='sqlite:///'+str(dst);env['AUTO_CREATE_SCHEMA']='false'
        def run(*args):
            subprocess.run([sys.executable,'-m','alembic',*args],cwd=ROOT,env=env,check=True)
        if not revisions:
            if version=='v04':
                # These two tables first appeared in v0.5. All other v0.4 tables
                # were exactly checked above; no legacy rows are modified.
                subprocess.run([sys.executable,'-c',
                    'from app.db import engine; from app.models import Device,DevicePairing; Device.__table__.create(engine); DevicePairing.__table__.create(engine)'],cwd=ROOT,env=env,check=True)
            run('stamp',BASELINE_REV if version=='v04' else V05_REV)
        run('upgrade','head');run('check')
        with sqlite3.connect(dst) as copy:
            if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or copy.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Post-migration integrity check failed')
            for name,count in counts.items():
                if copy.execute('SELECT count(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]!=count:
                    raise ValueError('Legacy row count changed: '+name)
        print(f'Migrated verified {version} copy to {dst}; source unchanged. Keep backup and test the copy before switching.')
    except Exception:
        if created and dst.exists(): dst.unlink()
        raise

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(f'Migration failed safely: {exc}',file=sys.stderr);sys.exit(1)
