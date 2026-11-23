import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
import app.main as main

TOKEN = "local-test-token-not-for-production"

@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main.settings, "auto_create_schema", True)
    monkeypatch.setattr(main.settings, "service_token", TOKEN)
    def db_override():
        with Session() as session:
            yield session
    main.app.dependency_overrides[get_db] = db_override
    # Legacy v0.5 regression tests: replace auth ONLY in this fixture. Real v0.6
    # authentication and RBAC are tested separately without dependency overrides.
    from fastapi import Header, HTTPException
    from app import licenses, support, payments
    async def legacy_test_auth(authorization: str | None = Header(default=None)):
        if not main.settings.service_token: raise HTTPException(503, 'No test token')
        if authorization != 'Bearer ' + main.settings.service_token: raise HTTPException(401, 'Bad test token')
    def legacy_test_admin(actor_id):
        if str(actor_id) not in main.settings.admin_telegram_ids.split(','): raise HTTPException(403,'Denied')
    main.app.dependency_overrides[main.require_service] = legacy_test_auth
    for mod in (licenses, support, payments): monkeypatch.setattr(mod, '_admin', legacy_test_admin)
    with TestClient(main.app) as instance:
        yield instance
    main.app.dependency_overrides.clear()
    engine.dispose()

@pytest.fixture
def auth():
    return {"Authorization": "Bearer " + TOKEN}

def register(client, auth, uid=1001):
    return client.post("/v1/users", headers=auth, json={"telegram_id": uid, "username": "user"})

def test_health_is_public(client):
    assert client.get("/health").json()["status"] == "ok"

def test_api_requires_service_credential(client):
    assert client.post("/v1/users", json={"telegram_id": 1}).status_code == 401
    assert client.get("/v1/game/adapters", headers={"Authorization":"Bearer wrong"}).status_code == 401

def test_missing_config_fails_closed(client, monkeypatch, auth):
    monkeypatch.setattr(main.settings, "service_token", "")
    assert client.get("/v1/game/adapters", headers=auth).status_code == 503

def test_registration_is_idempotent_and_updates_username(client, auth):
    a = register(client, auth).json()
    b = client.post("/v1/users", headers=auth, json={"telegram_id":1001,"username":"new_name"}).json()
    assert a["user_id"] == b["user_id"]
    assert client.get("/v1/users/1001", headers=auth).json()["username"] == "new_name"

def test_unknown_user(client, auth):
    assert client.get("/v1/users/9", headers=auth).status_code == 404

def test_invalid_user_rejected(client, auth):
    assert client.post("/v1/users", headers=auth, json={"telegram_id":0}).status_code == 422

def test_disabled_game_adapters(client, auth):
    adapters = client.get("/v1/game/adapters", headers=auth).json()["adapters"]
    assert len(adapters) == 2 and not any(x["enabled"] for x in adapters)

def test_pairing_is_disabled_even_for_service(client, auth):
    register(client, auth)
    assert client.post("/v1/pairing", headers=auth, json={"platform":"radmir"}).status_code == 503
    assert client.post("/v1/pairing/confirm", headers=auth, json={"code":"ABCDEFGH","telegram_id":1001}).status_code == 503

def test_setting_save_and_user_isolation(client, auth):
    register(client, auth, 1001); register(client, auth, 1002)
    endpoint="/v1/users/1001/settings/radmir/sms"
    assert client.put(endpoint, headers=auth, json={"enabled":True}).status_code == 200
    assert client.get("/v1/users/1001/settings", headers=auth).json()["settings"][0]["enabled"] is True
    assert client.get("/v1/users/1002/settings", headers=auth).json()["settings"] == []
    assert client.put(endpoint, headers=auth, json={"enabled":False}).json()["enabled"] is False
    assert len(client.get("/v1/users/1001/settings", headers=auth).json()["settings"]) == 1

def test_setting_validates_platform_and_kind(client, auth):
    register(client, auth)
    assert client.put("/v1/users/1001/settings/other/sms", headers=auth, json={"enabled":True}).status_code == 422
    assert client.put("/v1/users/1001/settings/radmir/other", headers=auth, json={"enabled":True}).status_code == 422

def test_ticket_create_and_isolation(client, auth):
    register(client, auth, 1001); register(client, auth, 1002)
    r = client.post("/v1/users/1001/tickets", headers=auth, json={"category":"other","message":"Help"})
    assert r.status_code == 201 and r.json()["status"] == "open"
    assert len(client.get("/v1/users/1001/tickets", headers=auth).json()["tickets"]) == 1
    assert client.get("/v1/users/1002/tickets", headers=auth).json()["tickets"] == []

def test_blank_and_overlong_ticket_rejected(client, auth):
    register(client, auth)
    url = "/v1/users/1001/tickets"
    assert client.post(url, headers=auth, json={"category":"other","message":"   "}).status_code == 422
    assert client.post(url, headers=auth, json={"category":"other","message":"x"*2001}).status_code == 422

def test_no_fake_device_information(client, auth):
    register(client, auth)
    assert client.get("/v1/users/1001", headers=auth).json()["devices"] is None

# License APIs use the same trusted-service boundary as the rest of the local starter.
from uuid import uuid4

def issue(client, auth, target=1001, actor=9999, days=30, request_id=None):
    return client.post('/v1/admin/licenses', headers=auth, json={
        'actor_telegram_id': actor, 'target_telegram_id': target,
        'duration_days': days, 'request_id': str(request_id or uuid4())})

def activate(client, auth, key, user=1001):
    return client.post(f'/v1/users/{user}/licenses/activate', headers=auth, json={'key':key})

def test_admin_denied_when_not_configured(client, auth):
    register(client, auth)
    assert issue(client, auth).status_code == 403

def test_issue_requires_registered_target(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    assert issue(client, auth).status_code == 404

def test_activation_and_repeat_do_not_extend(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    issued = issue(client, auth).json()
    first = activate(client, auth, issued['key'])
    second = activate(client, auth, issued['key'])
    assert first.status_code == 200 and first.json()['status'] == 'active'
    assert first.json()['expires_at'] == second.json()['expires_at']
    listed = client.get('/v1/users/1001/licenses', headers=auth).json()['licenses']
    assert len(listed) == 1 and listed[0]['status'] == 'active'
    assert issued['key'] not in str(listed)

def test_license_key_cannot_be_activated_by_another_user(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth, 1001); register(client, auth, 1002)
    issued=issue(client, auth).json()
    assert activate(client, auth, issued['key'], 1002).status_code == 400
    assert client.get('/v1/users/1002/licenses', headers=auth).json()['licenses'] == []

def test_revoke_is_idempotent_and_prevents_activation(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    grant=issue(client, auth).json()
    url=f"/v1/admin/licenses/{grant['id']}/revoke"
    assert client.post(url, headers=auth, json={'actor_telegram_id':9999}).json()['status']=='revoked'
    assert client.post(url, headers=auth, json={'actor_telegram_id':9999}).json()['status']=='revoked'
    assert activate(client, auth, grant['key']).status_code == 400

def test_issue_request_id_prevents_duplicate_keys(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    rid=uuid4()
    assert issue(client, auth, request_id=rid).status_code == 201
    assert issue(client, auth, request_id=rid).status_code == 409
    assert len(client.get('/v1/users/1001/licenses', headers=auth).json()['licenses']) == 1

def test_extend_replay_and_conflicting_request_id(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    grant = issue(client, auth).json()
    original = activate(client, auth, grant['key']).json()['expires_at']
    url=f"/v1/admin/licenses/{grant['id']}/extend"
    body={'actor_telegram_id':9999, 'days':7, 'request_id':str(uuid4())}
    first=client.post(url, headers=auth, json=body)
    assert first.status_code == 200 and first.json()['replayed'] is False
    assert first.json()['expires_at'] != original
    repeated=client.post(url, headers=auth, json=body)
    assert repeated.json()['replayed'] is True
    assert repeated.json()['expires_at'] == first.json()['expires_at']
    body['days']=8
    assert client.post(url, headers=auth, json=body).status_code == 409

def test_extend_requires_activated_nonrevoked_grant(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    grant=issue(client, auth).json()
    url=f"/v1/admin/licenses/{grant['id']}/extend"
    body={'actor_telegram_id':9999,'days':7,'request_id':str(uuid4())}
    assert client.post(url,headers=auth,json=body).status_code == 409
    activate(client,auth,grant['key'])
    client.post(f"/v1/admin/licenses/{grant['id']}/revoke",headers=auth,json={'actor_telegram_id':9999})
    assert client.post(url,headers=auth,json=body).status_code == 409

def test_unauthorized_actor_cannot_issue_or_revoke(client, auth, monkeypatch):
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    grant=issue(client,auth).json()
    assert issue(client,auth,actor=3333).status_code == 403
    assert client.post(f"/v1/admin/licenses/{grant['id']}/revoke",headers=auth,json={'actor_telegram_id':3333}).status_code == 403

def test_license_endpoints_require_service_auth(client):
    assert client.get('/v1/users/1001/licenses').status_code == 401
    assert client.post('/v1/admin/licenses',json={'actor_telegram_id':9999,'target_telegram_id':1001,'duration_days':30,'request_id':str(uuid4())}).status_code == 401

def test_audit_does_not_store_plain_key(client, auth, monkeypatch):
    from sqlalchemy.orm import Session
    from app.models import LicenseGrant, AdminAudit
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    register(client, auth)
    grant=issue(client, auth).json()
    with Session(main.engine) as db:
        row=db.get(LicenseGrant, grant['id'])
        audit=db.query(AdminAudit).filter_by(grant_id=grant['id']).all()
        assert row.key_hash != grant['key'] and len(row.key_hash) == 64
        assert len(audit) == 1 and audit[0].action == 'license_issue'
        assert grant['key'] not in str(audit[0].__dict__)

def test_expired_grant_can_be_extended_from_now(client, auth, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import app.licenses as licenses
    monkeypatch.setattr(main.settings, 'admin_telegram_ids', '9999')
    initial=datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(licenses, '_now', lambda: initial)
    register(client, auth)
    grant=issue(client, auth, days=1).json()
    activate(client, auth, grant['key'])
    monkeypatch.setattr(licenses, '_now', lambda: initial + timedelta(days=2))
    assert client.get('/v1/users/1001/licenses', headers=auth).json()['licenses'][0]['status'] == 'expired'
    body={'actor_telegram_id':9999,'days':7,'request_id':str(uuid4())}
    res=client.post(f"/v1/admin/licenses/{grant['id']}/extend",headers=auth,json=body)
    assert res.status_code == 200 and res.json()['expires_at'].startswith('2026-01-10')

def create_test_ticket(client, auth, user=1001):
    return client.post(f'/v1/users/{user}/tickets',headers=auth,json={'category':'connection','message':'Connection problem'}).json()['id']

def test_support_conversation_and_ownership(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    register(client,auth,1001); register(client,auth,1002)
    t=create_test_ticket(client,auth)
    base=f'/v1/users/1001/tickets/{t}'
    assert client.get(f'/v1/users/1002/tickets/{t}',headers=auth).status_code==404
    assert client.get(base,headers=auth).json()['initial_message']=='Connection problem'
    user_msg={'request_id':str(uuid4()),'text':'More info'}
    assert client.post(base+'/messages',headers=auth,json=user_msg).json()['status']=='saved'
    admin_msg={'request_id':str(uuid4()),'text':'Try again','actor_telegram_id':9999}
    assert client.post(f'/v1/admin/tickets/{t}/messages',headers=auth,json=admin_msg).json()['status']=='saved'
    msg=client.get(base,headers=auth).json()['messages']
    assert [(m['author_type'],m['text']) for m in msg]==[('user','More info'),('admin','Try again')]
    assert client.get(f'/v1/admin/tickets/{t}?actor_telegram_id=9999',headers=auth).json()['telegram_id']==1001

def test_support_replay_conflict_and_close(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999'); register(client,auth)
    t=create_test_ticket(client,auth); url=f'/v1/admin/tickets/{t}/messages'
    body={'request_id':str(uuid4()),'text':'test reply','actor_telegram_id':9999}
    assert client.post(url,headers=auth,json=body).json()['replayed'] is False
    assert client.post(url,headers=auth,json=body).json()['replayed'] is True
    changed={**body,'text':'different'}
    assert client.post(url,headers=auth,json=changed).status_code==409
    close=f'/v1/users/1001/tickets/{t}/close'
    assert client.post(close,headers=auth).json()['status']=='closed'
    assert client.post(close,headers=auth).json()['status']=='closed'
    assert client.post(url,headers=auth,json={**body,'request_id':str(uuid4())}).status_code==409
    assert client.get('/v1/admin/tickets?actor_telegram_id=9999',headers=auth).json()['tickets']==[]

def test_support_admin_role_and_auth(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999'); register(client,auth)
    t=create_test_ticket(client,auth)
    assert client.get('/v1/admin/tickets?actor_telegram_id=33',headers=auth).status_code==403
    assert client.get(f'/v1/admin/tickets/{t}?actor_telegram_id=33',headers=auth).status_code==403
    assert client.post(f'/v1/admin/tickets/{t}/close',headers=auth,json={'actor_telegram_id':33}).status_code==403
    assert client.get(f'/v1/users/1001/tickets/{t}').status_code==401
    assert client.post(f'/v1/admin/tickets/{t}/close',headers=auth,json={'actor_telegram_id':9999}).json()['status']=='closed'

def test_support_rejects_empty_message(client,auth):
    register(client,auth); t=create_test_ticket(client,auth)
    url=f'/v1/users/1001/tickets/{t}/messages'
    assert client.post(url,headers=auth,json={'request_id':str(uuid4()),'text':'   '}).status_code==422

def test_support_ticket_creation_idempotence(client,auth):
    register(client,auth); uid=str(uuid4())
    body={'category':'other','message':'test','request_id':uid}
    first=client.post('/v1/users/1001/tickets',headers=auth,json=body)
    repeat=client.post('/v1/users/1001/tickets',headers=auth,json=body)
    assert first.status_code == repeat.status_code == 201
    assert first.json()['id'] == repeat.json()['id'] and repeat.json()['replayed'] is True
    assert client.post('/v1/users/1001/tickets',headers=auth,json={**body,'message':'different'}).status_code==409
    assert len(client.get('/v1/users/1001/tickets',headers=auth).json()['tickets'])==1

def test_bot_support_flow_with_fake_telegram_and_local_api(client,auth,monkeypatch):
    import asyncio, time
    from aiogram import Bot
    from aiogram.types import Update
    from aiogram.client.session.base import BaseSession
    import app.bot.main as bot_module
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    class FakeSession(BaseSession):
        def __init__(self): super().__init__(); self.methods=[]
        async def close(self): pass
        async def make_request(self, bot, method, timeout=None):
            self.methods.append(method); return True
        async def stream_content(self,url,headers=None,timeout=30,chunk_size=65536,raise_for_status=True):
            if False: yield b''
    async def fake_api(method,path,body=None):
        result=client.request(method,path,headers=auth,json=body)
        if result.status_code>=400: raise bot_module.ApiError(str(result.status_code))
        return result.json()
    monkeypatch.setattr(bot_module,'api',fake_api)
    monkeypatch.setattr(bot_module,'mint_telegram_session',lambda *args:'isolated-fake-session')
    monkeypatch.setattr(bot_module,'revoke_session',lambda *args:None)
    now=int(time.time())
    def msg(seq,user,text,command=False):
        item={'message_id':seq,'date':now,'chat':{'id':user,'type':'private'},'from':{'id':user,'is_bot':False,'first_name':'Test'},'text':text}
        if command: item['entities']=[{'type':'bot_command','offset':0,'length':len(text)}]
        return Update.model_validate({'update_id':seq,'message':item})
    def cb(seq,user,data):
        return Update.model_validate({'update_id':seq,'callback_query':{'id':f'c{seq}','from':{'id':user,'is_bot':False,'first_name':'Test'},'chat_instance':str(user),'data':data,'message':{'message_id':seq,'date':now,'chat':{'id':user,'type':'private'},'from':{'id':123456,'is_bot':True,'first_name':'Bot'}}}})
    async def run():
        session=FakeSession(); bot=Bot('123456:abcdefghijklmnopqrstuvwxyzABCDE12345678',session=session)
        for update in [msg(101,1001,'/start',True),cb(102,1001,'ticket_cat:license'),msg(103,1001,'Need help'),msg(104,9999,'/tickets',True),cb(105,9999,'admin_ticket_reply:1'),msg(106,9999,'We can help'),cb(107,1001,'ticket_view:1')]:
            await bot_module.dp.feed_update(bot,update)
        transcript=client.get('/v1/users/1001/tickets/1',headers=auth).json()
        assert transcript['category']=='license' and transcript['messages'][0]['text']=='We can help'
        assert any('We can help' in (getattr(x,'text',None) or '') for x in session.methods)
        await bot.session.close()
    asyncio.run(run())

def enqueue_support_notice(client,auth,monkeypatch,enabled=True):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    register(client,auth)
    if enabled:
        client.put('/v1/users/1001/settings/radmir/system',headers=auth,json={'enabled':True})
    ticket=create_test_ticket(client,auth)
    body={'actor_telegram_id':9999,'text':'Support reply','request_id':str(uuid4())}
    r=client.post(f'/v1/admin/tickets/{ticket}/messages',headers=auth,json=body)
    assert r.status_code==200
    return ticket,body

def test_support_notifications_opt_in_and_dedup(client,auth,monkeypatch):
    ticket, body=enqueue_support_notice(client,auth,monkeypatch,enabled=False)
    assert client.get('/v1/users/1001/notifications',headers=auth).json()['notifications']==[]
    client.put('/v1/users/1001/settings/hassle/system',headers=auth,json={'enabled':True})
    body['request_id']=str(uuid4())
    client.post(f'/v1/admin/tickets/{ticket}/messages',headers=auth,json=body)
    client.post(f'/v1/admin/tickets/{ticket}/messages',headers=auth,json=body)
    assert len(client.get('/v1/users/1001/notifications',headers=auth).json()['notifications'])==1

def test_worker_sends_and_records_telegram_acceptance(client,auth,monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from sqlalchemy.orm import sessionmaker
    import app.worker as worker
    enqueue_support_notice(client,auth,monkeypatch)
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=main.engine))
    class FakeBot:
        async def send_message(self,chat_id,text):
            assert chat_id==1001 and '№1' in text
            return SimpleNamespace(message_id=321)
    assert asyncio.run(worker.process_one(FakeBot())) is True
    rows=client.get('/v1/users/1001/notifications',headers=auth).json()['notifications']
    assert len(rows)==1 and rows[0]['status']=='sent' and rows[0]['attempts']==1
    assert asyncio.run(worker.process_one(FakeBot())) is False

def test_worker_retry_then_exhaustion(client,auth,monkeypatch):
    import asyncio
    from sqlalchemy.orm import sessionmaker, Session
    from app.models import NotificationJob
    import app.worker as worker
    enqueue_support_notice(client,auth,monkeypatch)
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=main.engine))
    class FailingBot:
        async def send_message(self,*args): raise TimeoutError('network down')
    for attempt in range(1,worker.MAX_ATTEMPTS+1):
        assert asyncio.run(worker.process_one(FailingBot())) is True
        with Session(main.engine) as db:
            job=db.query(NotificationJob).first()
            assert job.attempts==attempt
            assert job.status==('exhausted' if attempt==worker.MAX_ATTEMPTS else 'pending')
            if job.status=='pending': job.next_attempt_at=worker.now(); db.commit()

def test_worker_respects_disabled_notifications(client,auth,monkeypatch):
    from sqlalchemy.orm import sessionmaker,Session
    from app.models import NotificationJob
    import app.worker as worker
    enqueue_support_notice(client,auth,monkeypatch)
    client.put('/v1/users/1001/settings/radmir/system',headers=auth,json={'enabled':False})
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=main.engine))
    assert worker.claim_one() is None
    with Session(main.engine) as db: assert db.query(NotificationJob).first().status=='cancelled'

def test_worker_lease_recovery_and_old_token_rejected(client,auth,monkeypatch):
    from sqlalchemy.orm import sessionmaker,Session
    from datetime import timedelta
    from app.models import NotificationJob
    import app.worker as worker
    enqueue_support_notice(client,auth,monkeypatch)
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=main.engine))
    first=worker.claim_one(); assert first and worker.claim_one() is None
    with Session(main.engine) as db:
        job=db.query(NotificationJob).first(); job.lease_until=worker.now()-timedelta(seconds=1); db.commit()
    second=worker.claim_one(); assert second and second['id']==first['id'] and second['token']!=first['token']
    assert worker.finish(first,'sent',telegram_message_id=1) is False
    assert worker.finish(second,'sent',telegram_message_id=2) is True

def test_notifications_are_scoped_to_user(client,auth,monkeypatch):
    enqueue_support_notice(client,auth,monkeypatch)
    register(client,auth,1002)
    assert client.get('/v1/users/1002/notifications',headers=auth).json()['notifications']==[]

def test_permanent_telegram_error_is_terminal(client,auth,monkeypatch):
    import asyncio
    from sqlalchemy.orm import sessionmaker
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.methods import SendMessage
    import app.worker as worker
    enqueue_support_notice(client,auth,monkeypatch)
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=main.engine))
    class ForbiddenBot:
        async def send_message(self,*args):
            raise TelegramForbiddenError(method=SendMessage(chat_id=1001,text='x'),message='Forbidden')
    asyncio.run(worker.process_one(ForbiddenBot()))
    rows=client.get('/v1/users/1001/notifications',headers=auth).json()['notifications']
    assert rows[0]['status']=='failed' and rows[0]['attempts']==1

def test_two_sqlite_workers_claim_at_most_one(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session
    from app.models import User, SupportTicket, SupportMessage, NotificationJob, NotificationSetting
    import app.worker as worker
    engine=create_engine(f"sqlite:///{tmp_path / 'queue.db'}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        u=User(telegram_id=1001); db.add(u); db.flush()
        t=SupportTicket(user_id=u.id,category='other',message='test'); db.add(t); db.flush()
        m=SupportMessage(ticket_id=t.id,request_id=str(uuid4()),author_type='admin',author_telegram_id=9999,text='hello'); db.add(m); db.flush()
        db.add(NotificationSetting(user_id=u.id,platform='radmir',kind='system',enabled=True))
        db.add(NotificationJob(user_id=u.id,ticket_id=t.id,support_message_id=m.id)); db.commit()
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=engine))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:worker.claim_one(),range(2)))
    assert len([x for x in claims if x is not None]) == 1
    engine.dispose()

def setup_pairing(client,auth,monkeypatch,uid=1001):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    monkeypatch.setattr(main.settings,'device_pairing_enabled',True)
    register(client,auth,uid)
    grant=issue(client,auth,target=uid).json()
    assert activate(client,auth,grant['key'],uid).status_code==200
    return grant

def start_pair(client,platform='radmir'):
    return client.post('/v1/device/pairing/start',json={'platform':platform,'name':'Test device'}).json()

def confirm_pair(client,auth,pair,uid=1001):
    return client.post('/v1/pairing/confirm',headers=auth,json={'telegram_id':uid,'code':pair['code']})

def claim_pair(client,pair):
    return client.post('/v1/device/pairing/claim',json={'pairing_id':pair['pairing_id'],'claim_secret':pair['claim_secret']})

def test_pairing_fails_closed_by_default(client):
    assert client.post('/v1/device/pairing/start',json={'platform':'radmir','name':'local'}).status_code==503

def test_device_pairing_license_and_revocation(client,auth,monkeypatch):
    from sqlalchemy.orm import Session
    from app.models import Device,DevicePairing
    grant=setup_pairing(client,auth,monkeypatch)
    pair=start_pair(client)
    assert confirm_pair(client,auth,pair).status_code==200
    assert confirm_pair(client,auth,pair).status_code==400
    claim=claim_pair(client,pair); assert claim.status_code==200
    secret=claim.json()['device_token']; device_id=claim.json()['device_id']
    assert claim_pair(client,pair).status_code==400
    assert client.get('/v1/device/me',headers={'Authorization':'Bearer '+secret}).status_code==200
    assert client.get('/v1/device/me',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.get('/v1/users/1001/devices',headers={'Authorization':'Bearer '+secret}).status_code==401
    assert len(client.get('/v1/users/1001/devices',headers=auth).json()['devices'])==1
    with Session(main.engine) as db:
        d=db.get(Device,device_id); pp=db.get(DevicePairing,pair['pairing_id'])
        assert d.credential_hash != secret and pp.code_hash != pair['code'] and pp.claim_hash != pair['claim_secret']
    r=client.post(f'/v1/users/1001/devices/{device_id}/revoke',headers=auth)
    assert r.json()['status']=='revoked'
    assert client.get('/v1/device/me',headers={'Authorization':'Bearer '+secret}).status_code==401

def test_device_revoked_license_loses_access(client,auth,monkeypatch):
    grant=setup_pairing(client,auth,monkeypatch); pair=start_pair(client)
    confirm_pair(client,auth,pair); token=claim_pair(client,pair).json()['device_token']
    client.post(f"/v1/admin/licenses/{grant['id']}/revoke",headers=auth,json={'actor_telegram_id':9999})
    assert client.get('/v1/device/me',headers={'Authorization':'Bearer '+token}).status_code==403

def test_pairing_rejects_wrong_claim_and_user_without_license(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'device_pairing_enabled',True); register(client,auth)
    pair=start_pair(client)
    assert confirm_pair(client,auth,pair).status_code==403
    assert client.post('/v1/device/pairing/claim',json={'pairing_id':pair['pairing_id'],'claim_secret':'x'*32}).status_code==400

def test_device_limit_and_owner_revoke(client,auth,monkeypatch):
    setup_pairing(client,auth,monkeypatch); monkeypatch.setattr(main.settings,'device_limit',1)
    register(client,auth,1002)
    pair=start_pair(client); confirm_pair(client,auth,pair); did=claim_pair(client,pair).json()['device_id']
    pair2=start_pair(client); assert confirm_pair(client,auth,pair2).status_code==409
    assert client.post(f'/v1/users/1002/devices/{did}/revoke',headers=auth).status_code==404
    assert client.post(f'/v1/users/1001/devices/{did}/revoke',headers=auth).status_code==200
    assert confirm_pair(client,auth,pair2).status_code==200

def test_expired_pairing_code_rejected(client,auth,monkeypatch):
    from sqlalchemy.orm import Session
    from datetime import timedelta
    from app.models import DevicePairing
    import app.devices as devices
    setup_pairing(client,auth,monkeypatch)
    pair=start_pair(client)
    with Session(main.engine) as db:
        row=db.get(DevicePairing,pair['pairing_id']); row.expires_at=devices.timestamp()-timedelta(seconds=1);db.commit()
    assert confirm_pair(client,auth,pair).status_code==400

def test_ready_checks_database(client):
    assert client.get('/ready').json()['status']=='ready'

def test_plan_creation_requires_admin_and_never_fakes_payment(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999'); register(client,auth)
    plan={'request_id':str(uuid4()),'actor_telegram_id':333,'name':'Premium','price_minor':1000,'currency':'EUR','duration_days':30,'device_limit':2,'platform':'both'}
    assert client.post('/v1/admin/plans',headers=auth,json=plan).status_code==403
    plan['actor_telegram_id']=9999
    r=client.post('/v1/admin/plans',headers=auth,json=plan)
    assert r.status_code==201
    assert client.get('/v1/plans',headers=auth).json()['plans'][0]['price_minor']==1000
    assert client.post('/v1/payments',headers=auth,json={'plan_id':r.json()['id'],'telegram_id':1001}).status_code==503
    assert client.get('/v1/users/1001/licenses',headers=auth).json()['licenses']==[]

def test_plan_request_id_replay_and_conflict(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    plan={'request_id':str(uuid4()),'actor_telegram_id':9999,'name':'Test','price_minor':500,'currency':'EUR','duration_days':30,'device_limit':2,'platform':'both'}
    first=client.post('/v1/admin/plans',headers=auth,json=plan)
    second=client.post('/v1/admin/plans',headers=auth,json=plan)
    assert first.status_code==201 and first.json()['id']==second.json()['id']
    assert client.post('/v1/admin/plans',headers=auth,json={**plan,'price_minor':1000}).status_code==409
    assert len(client.get('/v1/plans',headers=auth).json()['plans'])==1

def test_admin_access_checks_identity(client,auth,monkeypatch):
    monkeypatch.setattr(main.settings,'admin_telegram_ids','9999')
    assert client.get('/v1/admin/access?actor_telegram_id=9999',headers=auth).status_code==200
    assert client.get('/v1/admin/access?actor_telegram_id=1',headers=auth).status_code==403
    assert client.get('/v1/admin/access?actor_telegram_id=9999').status_code==401

def test_error_log_is_sanitized_and_admin_only(client,auth,monkeypatch):
    import asyncio
    from sqlalchemy.orm import sessionmaker
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.methods import SendMessage
    import app.worker as worker
    enqueue_support_notice(client,auth,monkeypatch)
    monkeypatch.setattr(worker,'SessionLocal',sessionmaker(bind=main.engine))
    class BadBot:
        async def send_message(self,*args):
            raise TelegramForbiddenError(method=SendMessage(chat_id=1001,text='x'),message='secret details must not be logged')
    asyncio.run(worker.process_one(BadBot()))
    assert client.get('/v1/admin/errors?actor_telegram_id=7',headers=auth).status_code==403
    entries=client.get('/v1/admin/errors?actor_telegram_id=9999',headers=auth).json()['errors']
    assert len(entries)==1 and entries[0]['code']=='telegram_permanent'
    assert 'secret details' not in str(entries)

def test_pending_pairing_cannot_claim_after_device_or_license_revoked(client,auth,monkeypatch):
    grant=setup_pairing(client,auth,monkeypatch)
    p=start_pair(client); device=confirm_pair(client,auth,p).json()['device_id']
    client.post(f'/v1/users/1001/devices/{device}/revoke',headers=auth)
    assert claim_pair(client,p).status_code==403
    p2=start_pair(client); confirm_pair(client,auth,p2)
    client.post(f"/v1/admin/licenses/{grant['id']}/revoke",headers=auth,json={'actor_telegram_id':9999})
    assert claim_pair(client,p2).status_code==403
