"""PostgreSQL integration, real RBAC dependency and concurrent entitlement checks."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from app.db import Base,get_db
from app import auth
import app.main as main

URL=os.getenv('NORI_TEST_POSTGRES_URL')
pytestmark=pytest.mark.skipif(not URL,reason='NORI_TEST_POSTGRES_URL not configured')

@pytest.fixture
def pg_secure(monkeypatch):
    schema='nori_sec_'+uuid4().hex
    admin=create_engine(URL)
    with admin.begin() as c: c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(URL,connect_args={'options':f'-csearch_path={schema}'})
    Base.metadata.create_all(engine);Local=sessionmaker(bind=engine,autoflush=False)
    monkeypatch.setattr(auth,'SessionLocal',Local)
    monkeypatch.setattr(main.settings,'owner_telegram_ids','9000')
    monkeypatch.setattr(main.settings,'device_pairing_enabled',True)
    monkeypatch.setattr(main.settings,'auto_create_schema',False)
    def db_override():
        with Local() as db: yield db
    main.app.dependency_overrides[get_db]=db_override
    try:
        with TestClient(main.app) as client: yield client
    finally:
        main.app.dependency_overrides.clear();engine.dispose()
        with admin.begin() as c: c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

def test_pg_plan_limit_parallel_real_rbac(pg_secure):
    c=pg_secure
    def user(uid): return {'Authorization':'Bearer '+auth.mint_telegram_session(uid)}
    owner=user(9000);u=user(1001);other=user(2002)
    assert c.get('/v1/users/1001',headers=other).status_code==403
    assert c.post('/v1/admin/users/2002/role',headers=other,json={'role':'admin'}).status_code==403
    assert c.post('/v1/admin/users/2002/role',headers=owner,json={'role':'admin'}).status_code==200
    assert c.get('/v1/admin/users',headers=other).status_code==200
    p=c.post('/v1/admin/plans',headers=owner,json={'request_id':str(uuid4()),'actor_telegram_id':9000,'name':'One','price_minor':1,'currency':'EUR','duration_days':3,'device_limit':1,'platform':'radmir'}).json()
    g=c.post('/v1/admin/licenses/from-plan',headers=owner,json={'request_id':str(uuid4()),'actor_telegram_id':9000,'target_telegram_id':1001,'plan_id':p['id']}).json()
    assert c.post('/v1/users/1001/licenses/activate',headers=u,json={'key':g['key']}).status_code==200
    pairs=[c.post('/v2/device/pairings',json={'platform':'radmir_crmp','name':'test'}).json() for _ in range(2)]
    def confirm(x): return c.post('/v2/pairings/confirm',headers=u,json={'pairing_id':x['pairing_id'],'pairing_code':x['pairing_code'],'license_id':g['id']}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(confirm,pairs))
    assert sorted(results)==[200,409]
