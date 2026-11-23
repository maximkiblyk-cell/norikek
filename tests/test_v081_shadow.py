import json,os,subprocess,sys,sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from app.db import Base
from app.models import User,License,LicenseGrant,LicenseEntitlement,SubscriptionPlan
from scripts.license_shadow import report

@pytest.fixture(params=['sqlite','postgres'])
def db(request,tmp_path):
    from sqlalchemy.engine import make_url
    url=os.getenv('NORI_TEST_POSTGRES_URL') if request.param=='postgres' else 'sqlite:///'+str(tmp_path/'copy.db')
    if not url:pytest.skip('NORI_TEST_POSTGRES_URL not configured')
    admin=None;schema=None
    if request.param=='postgres':
        admin=create_engine(url);schema='v081_'+uuid4().hex
        with admin.begin() as c:c.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(url)
    Base.metadata.create_all(engine)
    now=datetime.now(timezone.utc)
    with engine.begin() as c:c.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'));c.execute(text("INSERT INTO alembic_version VALUES ('4dbfc4c29581')"))
    with Session(engine) as s:
        s.add(User(id=1,telegram_id=111));s.add(User(id=2,telegram_id=222));s.flush()
        s.add_all([License(id=1,user_id=1,key_hash='legacy_a',active=True,expires_at=now+timedelta(days=3)),License(id=2,user_id=2,key_hash='legacy_b',active=False,expires_at=now+timedelta(days=3))])
        plan=SubscriptionPlan(id=str(uuid4()),request_id=str(uuid4()),created_by=1,name='p',price_minor=1,currency='EUR',duration_days=30,device_limit=1,platform='hassle',enabled=True);s.add(plan)
        for i in (1,2):s.add(LicenseGrant(id=i,user_id=i,key_hash=('a' if i==1 else 'b')*64,issue_request_id=str(uuid4()),duration_days=30,activated_at=now-timedelta(days=1),expires_at=now+timedelta(days=3)))
        s.flush();s.add(LicenseEntitlement(grant_id=1,plan_id=plan.id,platform='hassle',device_limit=1));s.commit()
    yield engine,request.param
    engine.dispose()
    if admin:
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

def test_shadow_repeated_read_only(db):
    engine,kind=db
    with engine.connect() as c:
        if kind=='postgres':c.exec_driver_sql('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        else:c.exec_driver_sql('PRAGMA query_only=ON');c.exec_driver_sql('BEGIN')
        a=report(c);b=report(c)
        assert a['legacy']==b['legacy'] and a['grants']==b['grants'] and a['shadow']==b['shadow']
        assert [r['classification'] for r in a['legacy']]==['ambiguous','invalid']
        assert [r['classification'] for r in a['grants']]==['existing_canonical','ambiguous']
        assert a['shadow'][0]['v2_any_grant_allowed'] is True
        with pytest.raises(Exception):c.execute(text('DELETE FROM licenses'))
    with engine.connect() as c:assert c.execute(text('SELECT count(*) FROM licenses')).scalar_one()==2

def test_cli_read_only_and_no_overwrite(db,tmp_path):
    engine,kind=db
    if kind!='sqlite':return
    src=Path(engine.url.database);out=tmp_path/'report.json';cmd=[sys.executable,'scripts/license_shadow.py','--sqlite',str(src),'--output',str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stderr
    assert len(json.loads(out.read_text())['legacy'])==2
    assert subprocess.run(cmd,capture_output=True).returncode!=0
    assert (out.stat().st_mode & 0o777)==0o600

def seed_v06(url):
    engine=create_engine(url)
    now=datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(User(id=1,telegram_id=1001));s.flush()
        s.add(License(id=1,user_id=1,key_hash='legacy-opaque-not-a-token',active=True,expires_at=now+timedelta(days=30)))
        plan=SubscriptionPlan(id=str(uuid4()),request_id=str(uuid4()),created_by=1,name='p',price_minor=1,currency='EUR',duration_days=30,device_limit=1,platform='hassle',enabled=True);s.add(plan)
        grant=LicenseGrant(user_id=1,key_hash='b'*64,issue_request_id=str(uuid4()),duration_days=30,activated_at=now-timedelta(days=1),expires_at=now+timedelta(days=30));s.add(grant);s.flush();s.add(LicenseEntitlement(grant_id=grant.id,plan_id=plan.id,platform='hassle',device_limit=1));s.commit()
    engine.dispose()

def test_shadow_on_actual_sqlite_v06_copy(tmp_path):
    root=Path(__file__).resolve().parents[1];src=tmp_path/'old.db';dest=tmp_path/'copy.db';env={**os.environ,'DATABASE_URL':'sqlite:///'+str(src),'AUTO_CREATE_SCHEMA':'false'}
    subprocess.run([sys.executable,'-m','alembic','upgrade','f60e00000001'],cwd=root,env=env,check=True,capture_output=True)
    seed_v06(env['DATABASE_URL'])
    with sqlite3.connect(src) as a,sqlite3.connect(dest) as b:a.backup(b)
    import hashlib
    before=hashlib.sha256(src.read_bytes()).hexdigest()
    out=tmp_path/'before.json';cmd=[sys.executable,'scripts/license_shadow.py','--sqlite',str(src),'--output',str(out)]
    assert subprocess.run(cmd,cwd=root,capture_output=True).returncode==0
    env['DATABASE_URL']='sqlite:///'+str(dest);subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,check=True,capture_output=True)
    out2=tmp_path/'after.json';cmd=[sys.executable,'scripts/license_shadow.py','--sqlite',str(dest),'--output',str(out2)]
    assert subprocess.run(cmd,cwd=root,capture_output=True).returncode==0
    a=json.loads(out.read_text());b=json.loads(out2.read_text());assert a['legacy']==b['legacy'] and a['grants']==b['grants'] and a['shadow']==b['shadow']
    assert hashlib.sha256(src.read_bytes()).hexdigest()==before

def test_shadow_on_actual_postgres_v06_copy(tmp_path):
    from sqlalchemy.engine import make_url
    url=os.getenv('NORI_TEST_POSTGRES_URL')
    if not url:pytest.skip('NORI_TEST_POSTGRES_URL not configured')
    root=Path(__file__).resolve().parents[1];admin=create_engine(url,isolation_level='AUTOCOMMIT');suf=uuid4().hex[:12];src='v081_src_'+suf;dst='v081_copy_'+suf
    env={**os.environ,'AUTO_CREATE_SCHEMA':'false'}
    try:
        with admin.connect() as c:c.execute(text(f'CREATE DATABASE "{src}"'))
        source=make_url(url).set(database=src).render_as_string(hide_password=False);env['DATABASE_URL']=source
        subprocess.run([sys.executable,'-m','alembic','upgrade','f60e00000001'],cwd=root,env=env,check=True,capture_output=True);seed_v06(source)
        out=tmp_path/'before.json';env['SHADOW_DB']=source
        assert subprocess.run([sys.executable,'scripts/license_shadow.py','--postgres-url-env','SHADOW_DB','--output',str(out)],cwd=root,env=env,capture_output=True).returncode==0
        with admin.connect() as c:c.execute(text(f'CREATE DATABASE "{dst}" TEMPLATE "{src}"'))
        target=make_url(url).set(database=dst).render_as_string(hide_password=False);env['DATABASE_URL']=target
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,check=True,capture_output=True)
        out2=tmp_path/'after.json';env['SHADOW_DB']=target
        assert subprocess.run([sys.executable,'scripts/license_shadow.py','--postgres-url-env','SHADOW_DB','--output',str(out2)],cwd=root,env=env,capture_output=True).returncode==0
        a=json.loads(out.read_text());b=json.loads(out2.read_text());assert a['legacy']==b['legacy'] and a['grants']==b['grants'] and a['shadow']==b['shadow']
        e=create_engine(source)
        with e.connect() as c:assert c.execute(text('select version_num from alembic_version')).scalar_one()=='f60e00000001';assert c.execute(text('select count(*) from licenses')).scalar_one()==1
        e.dispose()
    finally:
        with admin.connect() as c:c.execute(text(f'DROP DATABASE IF EXISTS "{dst}" WITH (FORCE)'));c.execute(text(f'DROP DATABASE IF EXISTS "{src}" WITH (FORCE)'))
        admin.dispose()
