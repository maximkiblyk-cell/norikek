"""Upgrade a verified v0.6 SQLite copy; never write to the source."""
import argparse,hashlib,json,os,sqlite3,subprocess,sys
from pathlib import Path
from sqlite_schema import schema
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path);a=parser.parse_args()
    src=a.source.resolve();dst=a.destination.resolve()
    if not src.is_file() or src==dst or dst.exists() or not dst.parent.is_dir() or any(x in str(dst) for x in '?#'):raise ValueError('Source must exist; destination must be a new, distinct safe path')
    created=False
    try:
        with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as old:
            fd=os.open(dst,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);created=True
            with sqlite3.connect(dst) as copy:old.backup(copy)
        with sqlite3.connect(dst) as db:
            if db.execute('pragma integrity_check').fetchone()[0]!='ok' or db.execute('pragma foreign_key_check').fetchone():raise ValueError('Integrity check failed')
            if schema(db)!=json.loads((ROOT/'scripts/v06_sqlite_schema.json').read_text()):raise ValueError('Unknown or modified schema; manual migration required')
            if db.execute('select version_num from alembic_version').fetchall()!=[('f60e00000001',)]:raise ValueError('Unexpected revision')
            tables=[row[0] for row in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' and name!='alembic_version'")]
            counts={t:db.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
        env={**os.environ,'DATABASE_URL':'sqlite:///'+str(dst),'AUTO_CREATE_SCHEMA':'false'}
        for args in [('upgrade','head'),('check',)]:subprocess.run([sys.executable,'-m','alembic',*args],cwd=ROOT,env=env,check=True)
        with sqlite3.connect(dst) as db:
            if db.execute('pragma integrity_check').fetchone()[0]!='ok' or db.execute('pragma foreign_key_check').fetchone():raise ValueError('Post-migration integrity failed')
            if any(db.execute('select count(*) from "'+t.replace('"','""')+'"').fetchone()[0]!=count for t,count in counts.items()):raise ValueError('Legacy row count changed')
        print('Migration succeeded on copy; original not modified. Back up and test before cutover.')
    except Exception:
        if created and dst.exists():dst.unlink()
        raise
if __name__=='__main__':
    try:main()
    except Exception as exc:print('Migration failed safely:',exc,file=sys.stderr);sys.exit(1)
