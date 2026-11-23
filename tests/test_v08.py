"""v0.8 v2 tests: real FastAPI dependencies and isolated SQLite, no auth shim."""
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import hashlib,json,os,subprocess,sys,sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from app.db import Base,get_db
from app import auth
from app.models import User,LicenseGrant,LicenseEntitlement,SubscriptionPlan,Device,AccountAccess
from app.v2.models import PairingV2,RemoteCommand,GameEvent,GameEventJob
from app.v2 import event_worker
import app.main as main

@pytest.fixture(params=['sqlite','postgres'])
def ctx(request,tmp_path,monkeypatch):
    admin=None;schema=None
    if request.param=='postgres':
        url=os.getenv('NORI_TEST_POSTGRES_URL')
        if not url: pytest.skip('NORI_TEST_POSTGRES_URL not configured')
        schema='v08_test_'+uuid4().hex;admin=create_engine(url)
        with admin.begin() as conn:conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else: engine=create_engine('sqlite:///'+str(tmp_path/'api.db'),connect_args={'check_same_thread':False,'timeout':15})
    Base.metadata.create_all(engine);Local=sessionmaker(bind=engine,autoflush=False)
    monkeypatch.setattr(auth,'SessionLocal',Local);monkeypatch.setattr(event_worker,'SessionLocal',Local)
    monkeypatch.setattr(main.settings,'auto_create_schema',False);monkeypatch.setattr(main.settings,'owner_telegram_ids','9000')
    monkeypatch.setattr(main.settings,'v2_approved_event_types','sms');monkeypatch.setattr(main.settings,'v2_approved_command_types','test_command')
    def override():
        with Local() as db:yield db
    main.app.dependency_overrides[get_db]=override
    with TestClient(main.app) as c:yield c,Local
    main.app.dependency_overrides.clear();engine.dispose()
    if admin:
        with admin.begin() as conn:conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

def session(uid):return {'Authorization':'Bearer '+auth.mint_telegram_session(uid)}
def make_grant(Local,uid=1001,platform='both',device_limit=1,days=30):
    moment=datetime.now(timezone.utc)
    with Local() as db:
        user=db.query(User).filter_by(telegram_id=uid).one();plan=SubscriptionPlan(id=str(uuid4()),request_id=str(uuid4()),created_by=9000,name='Test',price_minor=10,currency='EUR',duration_days=30,device_limit=device_limit,platform=platform,enabled=True);db.add(plan)
        grant=LicenseGrant(user_id=user.id,key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),issue_request_id=str(uuid4()),duration_days=30,activated_at=moment-timedelta(minutes=1),expires_at=moment+timedelta(days=days));db.add(grant);db.flush();db.add(LicenseEntitlement(grant_id=grant.id,plan_id=plan.id,platform=platform,device_limit=device_limit));db.commit();return grant.id

def start(c):
    r=c.post('/v2/device/pairings',json={'platform':'hassle_rp_2','name':'Test PC'});assert r.status_code==201,r.text;return r.json()
def preview(c,p,headers):return c.post('/v2/pairings/preview',headers=headers,json={'pairing_code':p['pairing_code']})
def confirm(c,p,headers,g):return c.post('/v2/pairings/confirm',headers=headers,json={'pairing_id':p['pairing_id'],'pairing_code':p['pairing_code'],'license_id':g})
def claim(c,p):return c.post('/v2/device/pairings/claim',json={'pairing_id':p['pairing_id'],'claim_secret':p['claim_secret']})
def paired(ctx):
    c,Local=ctx;u=session(1001);g=make_grant(Local);p=start(c);assert preview(c,p,u).status_code==200;assert confirm(c,p,u,g).status_code==200
    r=claim(c,p);assert r.status_code==200,r.text;d=r.json();return u,g,p,d,{'Authorization':'Bearer '+d['device_credential']}

def test_pairing_replay_revoke_expiration_and_secret_storage(ctx):
    c,Local=ctx;u,g,p,d,dh=paired(ctx);assert claim(c,p).status_code==409
    access=c.get('/v2/device/access',headers=dh);assert access.status_code==200 and access.json()['license_id']==g and access.headers['cache-control']=='no-store'
    with Local() as db:
        pair=db.get(PairingV2,p['pairing_id']);device=db.get(Device,d['device_id'])
        assert pair.code_hash!=p['pairing_code'] and pair.claim_hash!=p['claim_secret'] and device.credential_hash!=d['device_credential']
    assert c.post('/v2/devices/'+d['device_id']+'/revoke',headers=u).status_code==200
    assert c.get('/v2/device/access',headers=dh).status_code==401
    pair2=start(c)
    with Local() as db:db.get(PairingV2,pair2['pairing_id']).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert preview(c,pair2,u).status_code==410
    assert claim(c,pair2).status_code==410

def test_limit_platform_account_and_untrusted_ids(ctx):
    c,Local=ctx;u,g,p,d,dh=paired(ctx);pair2=start(c);assert confirm(c,pair2,u,g).status_code==409
    other=session(1002);assert confirm(c,pair2,other,g).status_code==403
    assert c.post('/v2/device/pairings',json={'platform':'hassle_rp_2','name':'X','device_id':str(uuid4())}).status_code==422
    assert c.post('/v2/device/pairings',json={'platform':'hassle_rp_2','name':'X','user_id':1001}).status_code==422
    with Local() as db:db.get(LicenseEntitlement,g).platform='radmir';db.commit()
    assert c.get('/v2/device/access',headers=dh).status_code==403
    with Local() as db:db.get(LicenseEntitlement,g).platform='both';db.get(LicenseGrant,g).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert c.get('/v2/device/access',headers=dh).status_code==403
    with Local() as db:db.get(LicenseGrant,g).expires_at=datetime.now(timezone.utc)+timedelta(days=1);urow=db.query(User).filter_by(telegram_id=1001).one();db.add(AccountAccess(user_id=urow.id,role='user',disabled=True));db.commit()
    assert c.get('/v2/device/access',headers=dh).status_code==403

def test_no_snapshot_and_rbac(ctx):
    c,Local=ctx;u=session(1001);other=session(1002);owner=session(9000);g=make_grant(Local)
    with Local() as db:db.delete(db.get(LicenseEntitlement,g));db.commit()
    p=start(c);assert confirm(c,p,u,g).status_code==403
    assert confirm(c,p,other,g).status_code==403
    assert c.post('/v2/pairings/preview',json={'pairing_code':p['pairing_code']}).status_code==401
    assert c.post('/v1/admin/users/1002/role',headers=u,json={'role':'admin'}).status_code==403
    assert c.post('/v1/admin/users/1002/role',headers=owner,json={'role':'admin'}).status_code==200
    assert c.post('/v1/admin/users/1001/disabled',headers=other,json={'disabled':True}).status_code==200
    assert c.post('/v1/admin/users/9000/disabled',headers=other,json={'disabled':True}).status_code==403

def test_pair_cancel_and_lost_claim(ctx):
    c,Local=ctx;u,g,p,d,dh=paired(ctx)
    r=c.post('/v2/pairings/'+p['pairing_id']+'/cancel',headers=u);assert r.status_code==200
    assert c.post('/v2/pairings/'+p['pairing_id']+'/cancel',headers=u).status_code==200
    assert c.get('/v2/device/access',headers=dh).status_code==401
    assert claim(c,p).status_code==409

def test_parallel_confirm_last_slot(ctx):
    c,Local=ctx;u=session(1001);g=make_grant(Local);p1=start(c);p2=start(c)
    with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(lambda p:confirm(c,p,u,g).status_code,[p1,p2]))
    assert sorted(statuses)==[200,409]

def test_rate_limit_and_redaction(ctx):
    c,Local=ctx;u=session(1001);secret='B'*16
    for _ in range(15):assert c.post('/v2/pairings/preview',headers=u,json={'pairing_code':secret}).status_code==404
    assert c.post('/v2/pairings/preview',headers=u,json={'pairing_code':secret}).status_code==429
    r=c.post('/v2/device/pairings/claim',json={'pairing_id':'BAD','claim_secret':'SENSITIVE_SECRET_VALUE'})
    assert r.status_code==422 and 'SENSITIVE_SECRET_VALUE' not in r.text

def create_command(c,u,d,key=None):
    return c.post('/v2/commands',headers=u,json={'device_id':d['device_id'],'idempotency_key':key or uuid4().hex,'command_type':'test_command','payload':{'x':1},'ttl_seconds':300})
def test_commands_receipt_retry_timeout_cancel_and_fresh_access(ctx):
    c,Local=ctx;u,g,p,d,dh=paired(ctx);key=uuid4().hex;r=create_command(c,u,d,key);assert r.status_code==201
    cid=r.json()['command_id'];assert create_command(c,u,d,key).json()['replayed']
    assert c.post('/v2/commands',headers=u,json={'device_id':d['device_id'],'idempotency_key':key,'command_type':'test_command','payload':{'x':2}}).status_code==409
    lease=c.post('/v2/device/commands/claim',headers=dh).json()['command'];assert lease['command_id']==cid
    with Local() as db:db.get(RemoteCommand,cid).lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert c.post('/v2/device/commands/'+cid+'/ack',headers=dh,json={'lease_token':lease['lease_token']}).status_code==409
    assert c.post('/v2/device/commands/claim',headers=dh).json()['command'] is None
    with Local() as db:db.get(RemoteCommand,cid).next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    redelivery=c.post('/v2/device/commands/claim',headers=dh).json()['command'];assert redelivery['attempts']==2
    token=redelivery['lease_token'];ack='/v2/device/commands/'+cid+'/ack';assert c.post(ack,headers=dh,json={'lease_token':token}).json()['status']=='ACKNOWLEDGED'
    assert c.post(ack,headers=dh,json={'lease_token':token}).json()['status']=='ACKNOWLEDGED'
    assert c.post('/v2/commands/'+cid+'/cancel',headers=u).status_code==409
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).json()['authorized']
    assert c.post('/v2/device/commands/'+cid+'/result',headers=dh,json={'lease_token':token,'result':'EXECUTED'}).status_code==503
    with Local() as db:db.get(LicenseGrant,g).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).status_code==403
    with Local() as db:db.get(LicenseGrant,g).expires_at=datetime.now(timezone.utc)+timedelta(days=1);db.get(RemoteCommand,cid).acknowledged_at=datetime.now(timezone.utc)-timedelta(seconds=121);db.commit()
    assert c.get('/v2/commands/'+cid,headers=u).json()['error_code']=='EXECUTION_UNKNOWN'
    second=create_command(c,u,d).json()['command_id'];assert c.post('/v2/commands/'+second+'/cancel',headers=u).json()['status']=='CANCELLED'
    assert c.post('/v2/device/commands/claim',headers=dh).json()['command'] is None

def test_events_dedup_and_separate_queue(ctx):
    c,Local=ctx;u,g,p,d,dh=paired(ctx);eid=str(uuid4());body={'event_id':eid,'event_type':'sms','payload':{'message':'only isolated test data'}}
    assert c.post('/v2/events',headers=dh,json=body).json()['replayed'] is False
    assert c.post('/v2/events',headers=dh,json=body).json()['replayed'] is True
    assert c.post('/v2/events',headers=dh,json={**body,'payload':{'message':'different'}}).status_code==409
    with Local() as db:assert db.query(GameEvent).count()==1 and db.query(GameEventJob).count()==1
    assert c.post('/v2/events',headers=dh,json={**body,'event_type':'unapproved'}).status_code==503

ROOT=Path(__file__).resolve().parents[1]
def test_v06_sqlite_copy_migration_preserves_rows_and_original(tmp_path):
    old=tmp_path/'old.db';copy=tmp_path/'copy.db';env={**os.environ,'DATABASE_URL':'sqlite:///'+str(old),'AUTO_CREATE_SCHEMA':'false'}
    subprocess.run([sys.executable,'-m','alembic','upgrade','f60e00000001'],cwd=ROOT,env=env,check=True,capture_output=True)
    with sqlite3.connect(old) as db:db.execute("insert into users (id,telegram_id,username,created_at) values (1,1001,'preserved','2026-01-01')")
    before=hashlib.sha256(old.read_bytes()).hexdigest();
    with sqlite3.connect(old) as source,sqlite3.connect(copy) as target:source.backup(target)
    env['DATABASE_URL']='sqlite:///'+str(copy)
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,check=True,capture_output=True)
    subprocess.run([sys.executable,'-m','alembic','check'],cwd=ROOT,env=env,check=True,capture_output=True)
    assert hashlib.sha256(old.read_bytes()).hexdigest()==before
    with sqlite3.connect(copy) as db:
        assert db.execute('select telegram_id,username from users').fetchall()==[(1001,'preserved')]
        assert db.execute('select version_num from alembic_version').fetchone()==('4dbfc4c29581',)
        assert db.execute("select count(*) from sqlite_master where name in ('v2_pairings','game_events','remote_commands','game_event_jobs')").fetchone()[0]==4

def test_v06_postgres_copy_migration_preserves_original():
    url=os.getenv('NORI_TEST_POSTGRES_URL')
    if not url:pytest.skip('NORI_TEST_POSTGRES_URL not configured')
    from sqlalchemy.engine import make_url
    admin=create_engine(url,isolation_level='AUTOCOMMIT');suffix=uuid4().hex[:12];src='v08_mig_src_'+suffix;dst='v08_mig_copy_'+suffix
    env={**os.environ,'AUTO_CREATE_SCHEMA':'false'}
    try:
        with admin.connect() as conn:conn.execute(text(f'CREATE DATABASE "{src}"'))
        source_url=make_url(url).set(database=src).render_as_string(hide_password=False)
        env['DATABASE_URL']=source_url
        subprocess.run([sys.executable,'-m','alembic','upgrade','f60e00000001'],cwd=ROOT,env=env,check=True,capture_output=True)
        source=create_engine(source_url)
        with source.begin() as conn:conn.execute(text("INSERT INTO users (id,telegram_id,username,created_at) VALUES (1,1001,'preserved','2026-01-01')"))
        source.dispose()
        with admin.connect() as conn:conn.execute(text(f'CREATE DATABASE "{dst}" TEMPLATE "{src}"'))
        dest_url=make_url(url).set(database=dst).render_as_string(hide_password=False);env['DATABASE_URL']=dest_url
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,check=True,capture_output=True)
        subprocess.run([sys.executable,'-m','alembic','check'],cwd=ROOT,env=env,check=True,capture_output=True)
        for dburl,revision in [(source_url,'f60e00000001'),(dest_url,'4dbfc4c29581')]:
            engine=create_engine(dburl)
            with engine.connect() as conn:
                assert conn.execute(text('select telegram_id,username from users')).all()==[(1001,'preserved')]
                assert conn.execute(text('select version_num from alembic_version')).scalar_one()==revision
            engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{dst}" WITH (FORCE)'))
            conn.execute(text(f'DROP DATABASE IF EXISTS "{src}" WITH (FORCE)'))
        admin.dispose()

def test_safe_v06_copy_script_and_unknown_schema(tmp_path):
    old=tmp_path/'old.db';dest=tmp_path/'new.db';env={**os.environ,'DATABASE_URL':'sqlite:///'+str(old),'AUTO_CREATE_SCHEMA':'false'}
    subprocess.run([sys.executable,'-m','alembic','upgrade','f60e00000001'],cwd=ROOT,env=env,check=True,capture_output=True)
    before=hashlib.sha256(old.read_bytes()).hexdigest()
    result=subprocess.run([sys.executable,'scripts/migrate_v06_sqlite_copy.py',str(old),str(dest)],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert hashlib.sha256(old.read_bytes()).hexdigest()==before
    assert subprocess.run([sys.executable,'scripts/migrate_v06_sqlite_copy.py',str(old),str(dest)],cwd=ROOT,capture_output=True).returncode!=0
    bad=tmp_path/'bad.db';out=tmp_path/'badout.db'
    with sqlite3.connect(bad) as db:db.execute('create table unknown(id integer)')
    assert subprocess.run([sys.executable,'scripts/migrate_v06_sqlite_copy.py',str(bad),str(out)],cwd=ROOT,capture_output=True).returncode!=0
    assert not out.exists()

def test_changed_entitlement_and_command_type_are_rechecked(ctx,monkeypatch):
    c,Local=ctx;u,g,p,d,dh=paired(ctx)
    r=create_command(c,u,d);cid=r.json()['command_id'];lease=c.post('/v2/device/commands/claim',headers=dh).json()['command'];token=lease['lease_token']
    assert c.post('/v2/device/commands/'+cid+'/ack',headers=dh,json={'lease_token':token}).status_code==200
    monkeypatch.setattr(main.settings,'v2_approved_command_types','')
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).status_code==503
    monkeypatch.setattr(main.settings,'v2_approved_command_types','test_command')
    with Local() as db:db.get(LicenseEntitlement,g).platform='radmir';db.commit()
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).status_code==403
    with Local() as db:db.get(LicenseEntitlement,g).platform='both';db.commit()
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).status_code==200
    assert c.post('/v2/devices/'+d['device_id']+'/revoke',headers=u).status_code==200
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).status_code==401

def test_plan_issue_activation_snapshot_consistent(ctx):
    c,Local=ctx;u=session(1001);owner=session(9000)
    r=c.post('/v1/admin/plans',headers=owner,json={'request_id':str(uuid4()),'actor_telegram_id':9000,'name':'Test','price_minor':1,'currency':'EUR','duration_days':7,'device_limit':1,'platform':'hassle'});assert r.status_code==201
    r=c.post('/v1/admin/licenses/from-plan',headers=owner,json={'request_id':str(uuid4()),'actor_telegram_id':9000,'target_telegram_id':1001,'plan_id':r.json()['id']});assert r.status_code==201;grant=r.json()
    assert c.post('/v1/users/1001/licenses/activate',headers=u,json={'key':grant['key']}).status_code==200
    assert c.get('/v2/licenses',headers=u).json()['licenses'][0]['allowed'] is True
    assert c.get('/v1/users/1001/licenses',headers=u).json()['licenses'][0]['access']['allowed'] is True
    p=start(c);assert confirm(c,p,u,grant['id']).status_code==200
    assert confirm(c,p,u,grant['id']).status_code==409
    assert claim(c,p).status_code==200

def test_event_worker_optin_and_retry(ctx):
    import asyncio
    from app.models import NotificationSetting
    c,Local=ctx;u,g,p,d,dh=paired(ctx);eid=str(uuid4())
    with Local() as db:
        dev=db.get(Device,d['device_id']);db.add(NotificationSetting(user_id=dev.user_id,platform=dev.platform,kind='sms',enabled=True));db.commit()
    assert c.post('/v2/events',headers=dh,json={'event_id':eid,'event_type':'sms','payload':{'private':'never sent'}}).status_code==202
    class Unavailable:
        async def send_message(self,*args):raise OSError('test failure must not be logged')
    class Delivery:
        def __init__(self):self.messages=[]
        async def send_message(self,uid,msg):self.messages.append(msg)
    assert asyncio.run(event_worker.process_one(Unavailable()))
    with Local() as db:
        job=db.query(GameEventJob).one();assert job.status=='pending' and job.error_code=='temporary_error';job.next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    client=Delivery();assert asyncio.run(event_worker.process_one(client))
    assert client.messages and 'never sent' not in client.messages[0]
    with Local() as db:assert db.query(GameEventJob).one().status=='sent'

def test_command_expiry_retry_exhaustion_and_other_user(ctx):
    c,Local=ctx;u,g,p,d,dh=paired(ctx);other=session(1002);cid=create_command(c,u,d).json()['command_id']
    assert c.get('/v2/commands/'+cid,headers=other).status_code==404
    assert c.post('/v2/commands/'+cid+'/cancel',headers=other).status_code==404
    lease=c.post('/v2/device/commands/claim',headers=dh).json()['command']
    with Local() as db:
        cmd=db.get(RemoteCommand,cid);cmd.lease_until=datetime.now(timezone.utc)-timedelta(seconds=1);cmd.attempts=5;db.commit()
    assert c.post('/v2/device/commands/claim',headers=dh).json()['command'] is None
    assert c.get('/v2/commands/'+cid,headers=u).json()['error_code']=='ACK_TIMEOUT'
    cid2=create_command(c,u,d).json()['command_id']
    with Local() as db:db.get(RemoteCommand,cid2).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert c.post('/v2/device/commands/claim',headers=dh).json()['command'] is None
    assert c.get('/v2/commands/'+cid2,headers=u).json()['status']=='EXPIRED'

def test_unactivated_grant_summary_is_denied_and_safe(ctx):
    c,Local=ctx;u=session(1001);g=make_grant(Local)
    with Local() as db:grant=db.get(LicenseGrant,g);grant.activated_at=None;grant.expires_at=None;db.commit()
    r=c.get('/v2/licenses',headers=u);assert r.status_code==200
    assert r.json()['licenses'][0]['reason']=='LICENSE_NOT_ACTIVE' and r.json()['licenses'][0]['expires_at'] is None
    assert c.get('/v1/users/1001',headers=u).json()['license'] is None

def test_isolated_executor_is_not_game_execution(ctx):
    """Synthetic in-process executor tests sequencing only, never the production verifier."""
    import hashlib
    c,Local=ctx;u,g,p,d,dh=paired(ctx);cid=create_command(c,u,d).json()['command_id']
    command=c.post('/v2/device/commands/claim',headers=dh).json()['command'];token=command['lease_token']
    assert c.post('/v2/device/commands/'+cid+'/ack',headers=dh,json={'lease_token':token}).json()['status']=='ACKNOWLEDGED'
    assert c.get('/v2/commands/'+cid,headers=u).json()['status']=='ACKNOWLEDGED'
    assert c.post('/v2/device/commands/'+cid+'/authorize',headers=dh,json={'lease_token':token}).json()['authorized']
    # Local calculation has no game integration and cannot certify production execution.
    result=hashlib.sha256(b'isolated test').hexdigest();assert len(result)==64
    r=c.post('/v2/device/commands/'+cid+'/result',headers=dh,json={'lease_token':token,'result':'EXECUTED'})
    assert r.status_code==503 and c.get('/v2/commands/'+cid,headers=u).json()['status']=='ACKNOWLEDGED'
