"""Security tests use the real dependency, not the legacy regression auth shim."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.models import User, AccountAccess, AuthSession
from app import auth
import app.main as main

@pytest.fixture
def secure(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Local=sessionmaker(bind=engine,autoflush=False)
    monkeypatch.setattr(auth,'SessionLocal',Local)
    monkeypatch.setattr(main.settings,'owner_telegram_ids','9000')
    monkeypatch.setattr(main.settings,'service_token','old-global-service-token-123456789')
    monkeypatch.setattr(main.settings,'auto_create_schema',False)
    def db_override():
        with Local() as db: yield db
    main.app.dependency_overrides[get_db]=db_override
    with TestClient(main.app) as client:
        yield client,Local
    main.app.dependency_overrides.clear()
    engine.dispose()

def make_session(uid):
    return {'Authorization':'Bearer '+auth.mint_telegram_session(uid)}

def test_shared_service_token_rejected_and_user_isolation(secure):
    client,Local=secure; a=make_session(1001); b=make_session(1002)
    assert client.get('/v1/users/1001',headers=a).status_code == 200
    assert client.get('/v1/users/1002',headers=a).status_code == 403
    assert client.post('/v1/users',headers=a,json={'telegram_id':1002}).status_code == 403
    assert client.post('/v1/pairing/confirm',headers=a,json={'telegram_id':1002,'code':'ABCDEFGHIJKLMNOP'}).status_code in (403,503)
    assert client.get('/v1/users/1001',headers={'Authorization':'Bearer old-global-service-token-123456789'}).status_code == 401
    assert client.get('/v1/users/1001',headers=b).status_code == 403

def test_rbac_actor_spoof_rejected(secure):
    client,Local=secure; owner=make_session(9000); user=make_session(1001)
    assert client.get('/v1/admin/access?actor_telegram_id=9000',headers=user).status_code == 403
    assert client.get('/v1/admin/access?actor_telegram_id=1001',headers=owner).status_code == 403
    assert client.get('/v1/admin/access?actor_telegram_id=9000',headers=owner).status_code == 200
    body={'actor_telegram_id':9000,'target_telegram_id':1001,'duration_days':30,'request_id':str(uuid4())}
    assert client.post('/v1/admin/licenses',headers=user,json=body).status_code==403
    assert client.post('/v1/admin/licenses',headers=owner,json=body).status_code==201

def test_expired_revoked_and_disabled_sessions(secure):
    client,Local=secure; user=make_session(1001); raw=user['Authorization'][7:]
    with Local() as db:
        db.get(AuthSession,auth.digest(raw)).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
    assert client.get('/v1/users/1001',headers=user).status_code==401
    user=make_session(1001);raw=user['Authorization'][7:];auth.revoke_session(raw)
    assert client.get('/v1/users/1001',headers=user).status_code==401
    user=make_session(1001)
    with Local() as db:
        u=db.query(User).filter_by(telegram_id=1001).one();db.add(AccountAccess(user_id=u.id,role='user',disabled=True));db.commit()
    assert client.get('/v1/users/1001',headers=user).status_code==403
    with pytest.raises(PermissionError): auth.mint_telegram_session(1001)

def test_owner_admin_user_rbac_and_revocation(secure):
    client,Local=secure; owner=make_session(9000); admin=make_session(2002); user=make_session(1001)
    url='/v1/admin/users/2002/role'
    assert client.post(url,headers=admin,json={'role':'admin'}).status_code==403
    assert client.post(url,headers=owner,json={'role':'admin'}).json()['role']=='admin'
    assert client.get('/v1/admin/users',headers=admin).status_code==200
    assert client.post('/v1/admin/users/1001/role',headers=admin,json={'role':'admin'}).status_code==403
    assert client.post('/v1/admin/users/9000/disabled',headers=admin,json={'disabled':True}).status_code==403
    assert client.post('/v1/admin/users/2002/disabled',headers=admin,json={'disabled':True}).status_code==403
    assert client.post('/v1/admin/users/1001/disabled',headers=admin,json={'disabled':True}).status_code==200
    assert client.get('/v1/users/1001',headers=user).status_code==401
    assert client.post('/v1/admin/users/1001/disabled',headers=owner,json={'disabled':False}).status_code==200
    assert client.get('/v1/users/1001',headers=user).status_code==401
    assert client.get('/v1/users/1001',headers=make_session(1001)).status_code==200
    assert client.post(url,headers=owner,json={'role':'user'}).json()['role']=='user'
    assert client.get('/v1/admin/users',headers=admin).status_code==403

def test_plan_snapshot_duration_platform_device_limit_and_disable(secure,monkeypatch):
    client,Local=secure; monkeypatch.setattr(main.settings,'device_pairing_enabled',True)
    owner=make_session(9000);user=make_session(1001)
    plan={'request_id':str(uuid4()),'actor_telegram_id':9000,'name':'Radmir 7','price_minor':100,
          'currency':'EUR','duration_days':7,'device_limit':1,'platform':'radmir'}
    p=client.post('/v1/admin/plans',headers=owner,json=plan)
    assert p.status_code==201; pid=p.json()['id']
    body={'request_id':str(uuid4()),'actor_telegram_id':9000,'target_telegram_id':1001,'plan_id':pid}
    issued=client.post('/v1/admin/licenses/from-plan',headers=owner,json=body)
    assert issued.status_code==201 and issued.json()['duration_days']==7
    key=issued.json()['key']
    first=client.post('/v1/users/1001/licenses/activate',headers=user,json={'key':key}).json()
    start=datetime.fromisoformat(first['activated_at']); end=datetime.fromisoformat(first['expires_at'])
    assert end-start==timedelta(days=7)
    ent=client.get('/v1/users/1001/licenses',headers=user).json()['licenses'][0]['entitlement']
    assert ent=={'plan_id':pid,'platform':'radmir','device_limit':1}
    wrong=client.post('/v1/device/pairing/start',json={'name':'other','platform':'hassle'}).json()
    assert client.post('/v1/pairing/confirm',headers=user,json={'telegram_id':1001,'code':wrong['code']}).status_code==409
    pair=client.post('/v1/device/pairing/start',json={'name':'test','platform':'radmir'}).json()
    assert client.post('/v1/pairing/confirm',headers=user,json={'telegram_id':1001,'code':pair['code']}).status_code==200
    token=client.post('/v1/device/pairing/claim',json={'pairing_id':pair['pairing_id'],'claim_secret':pair['claim_secret']}).json()['device_token']
    again=client.post('/v1/device/pairing/start',json={'name':'another','platform':'radmir'}).json()
    assert client.post('/v1/pairing/confirm',headers=user,json={'telegram_id':1001,'code':again['code']}).status_code==409
    assert client.post(f'/v1/admin/plans/{pid}/enabled',headers=owner,json={'enabled':False}).status_code==200
    assert client.post('/v1/admin/licenses/from-plan',headers=owner,json={**body,'request_id':str(uuid4())}).status_code==404
    assert client.get('/v1/device/me',headers={'Authorization':'Bearer '+token}).status_code==200
    assert client.post('/v1/admin/users/1001/disabled',headers=owner,json={'disabled':True}).status_code==200
    assert client.get('/v1/device/me',headers={'Authorization':'Bearer '+token}).status_code==403
