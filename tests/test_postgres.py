"""Optional tests: NORI_TEST_POSTGRES_URL must point to a disposable test database."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from app.db import Base, get_db
import app.main as main
from app.models import User, SupportTicket, SupportMessage, NotificationJob, NotificationSetting

URL = os.getenv('NORI_TEST_POSTGRES_URL')
pytestmark = pytest.mark.skipif(not URL, reason='NORI_TEST_POSTGRES_URL not configured')

@pytest.fixture
def pg_env(monkeypatch):
    # Never touch public schema: create and drop only a fresh random test schema.
    schema='nori_test_'+uuid4().hex
    admin=create_engine(URL)
    with admin.begin() as conn: conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(URL,connect_args={'options':f'-csearch_path={schema}'})
    Base.metadata.create_all(engine)
    Local=sessionmaker(bind=engine,autoflush=False)
    def db_override():
        with Local() as db: yield db
    monkeypatch.setattr(main.settings,'service_token','pg-test-only-token')
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    monkeypatch.setattr(main.settings,'device_pairing_enabled',True)
    monkeypatch.setattr(main.settings,'device_limit',1)
    monkeypatch.setattr(main.settings,'auto_create_schema',False)
    main.app.dependency_overrides[get_db]=db_override
    # Isolated compatibility fixture for old behavior; new auth tested separately.
    from fastapi import Header, HTTPException
    from app import licenses, support, payments
    async def legacy_test_auth(authorization: str | None = Header(default=None)):
        if authorization != 'Bearer ' + main.settings.service_token: raise HTTPException(401,'Bad test token')
    def legacy_test_admin(actor_id):
        if str(actor_id) not in main.settings.admin_telegram_ids.split(','): raise HTTPException(403,'Denied')
    main.app.dependency_overrides[main.require_service]=legacy_test_auth
    for mod in (licenses,support,payments): monkeypatch.setattr(mod,'_admin',legacy_test_admin)
    try:
        with TestClient(main.app) as client:
            yield client,engine,Local,{'Authorization':'Bearer pg-test-only-token'}
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
        with admin.begin() as conn: conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

def _registered_grant(client,auth):
    assert client.post('/v1/users',headers=auth,json={'telegram_id':1001}).status_code==200
    g=client.post('/v1/admin/licenses',headers=auth,json={'actor_telegram_id':9999,'target_telegram_id':1001,'duration_days':30,'request_id':str(uuid4())}).json()
    assert client.post('/v1/users/1001/licenses/activate',headers=auth,json={'key':g['key']}).status_code==200
    return g

def test_pg_parallel_pairings_respect_device_limit(pg_env):
    client,engine,Local,auth=pg_env
    _registered_grant(client,auth)
    codes=[client.post('/v1/device/pairing/start',json={'name':'Test','platform':'radmir'}).json() for _ in range(2)]
    def confirm(p):
        return client.post('/v1/pairing/confirm',headers=auth,json={'telegram_id':1001,'code':p['code']}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(confirm,codes))
    assert sorted(statuses)==[200,409]
    assert len(client.get('/v1/users/1001/devices',headers=auth).json()['devices'])==1

def test_pg_device_license_revoke_stops_access(pg_env):
    client,engine,Local,auth=pg_env; grant=_registered_grant(client,auth)
    pair=client.post('/v1/device/pairing/start',json={'name':'Test','platform':'hassle'}).json()
    assert client.post('/v1/pairing/confirm',headers=auth,json={'telegram_id':1001,'code':pair['code']}).status_code==200
    claim=client.post('/v1/device/pairing/claim',json={'pairing_id':pair['pairing_id'],'claim_secret':pair['claim_secret']}).json()
    dev_auth={'Authorization':'Bearer '+claim['device_token']}
    assert client.get('/v1/device/me',headers=dev_auth).status_code==200
    client.post(f"/v1/admin/licenses/{grant['id']}/revoke",headers=auth,json={'actor_telegram_id':9999})
    assert client.get('/v1/device/me',headers=dev_auth).status_code==403

def test_pg_parallel_workers_claim_once(pg_env,monkeypatch):
    import app.worker as worker
    client,engine,Local,auth=pg_env
    with Session(engine) as db:
        user=User(telegram_id=1001);db.add(user);db.flush()
        ticket=SupportTicket(user_id=user.id,category='other',message='test');db.add(ticket);db.flush()
        message=SupportMessage(ticket_id=ticket.id,request_id=str(uuid4()),author_type='admin',author_telegram_id=9999,text='reply');db.add(message);db.flush()
        db.add(NotificationSetting(user_id=user.id,platform='radmir',kind='system',enabled=True))
        db.add(NotificationJob(user_id=user.id,ticket_id=ticket.id,support_message_id=message.id));db.commit()
    monkeypatch.setattr(worker,'SessionLocal',Local)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:worker.claim_one(),range(2)))
    assert len([c for c in claims if c is not None])==1

def _claim_in_process(url, schema, barrier, out):
    import app.worker as worker
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    db_engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    worker.SessionLocal=sessionmaker(bind=db_engine)
    try:
        barrier.wait(timeout=10)
        claim=worker.claim_one()
        out.put(('ok',bool(claim)))
    except Exception as exc:
        out.put(('error',type(exc).__name__))
    finally:
        db_engine.dispose()

def test_pg_two_worker_processes_claim_once(pg_env):
    import multiprocessing as mp
    import sys
    if sys.platform == 'win32': pytest.skip('process test uses fork')
    client,engine,Local,auth=pg_env
    with Session(engine) as db:
        schema=db.execute(text('SELECT current_schema()')).scalar_one()
        user=User(telegram_id=1001);db.add(user);db.flush()
        ticket=SupportTicket(user_id=user.id,category='other',message='test');db.add(ticket);db.flush()
        message=SupportMessage(ticket_id=ticket.id,request_id=str(uuid4()),author_type='admin',author_telegram_id=9999,text='reply');db.add(message);db.flush()
        db.add(NotificationSetting(user_id=user.id,platform='radmir',kind='system',enabled=True))
        db.add(NotificationJob(user_id=user.id,ticket_id=ticket.id,support_message_id=message.id));db.commit()
    ctx=mp.get_context('fork'); barrier=ctx.Barrier(2); out=ctx.Queue()
    workers=[ctx.Process(target=_claim_in_process,args=(URL,schema,barrier,out)) for _ in range(2)]
    for process in workers: process.start()
    for process in workers: process.join(15)
    for process in workers:
        if process.is_alive(): process.terminate();process.join();pytest.fail('worker process timed out')
        assert process.exitcode==0
    outcomes=[out.get(timeout=3) for _ in workers]
    assert sorted(outcomes)==[('ok',False),('ok',True)]
