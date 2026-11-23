"""Real loopback HTTP integration: FastAPI/uvicorn + migrated SQLite file."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
from uuid import uuid4
import httpx
ROOT=Path(__file__).resolve().parents[1]

def test_real_uvicorn_pairing_and_revocation(tmp_path):
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    env={**os.environ,'DATABASE_URL':'sqlite:///'+str(tmp_path/'network.db'),'AUTO_CREATE_SCHEMA':'false','OWNER_TELEGRAM_IDS':'9000','BOT_TOKEN':''}
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,cwd=ROOT,check=True,capture_output=True)
    seed='''
from uuid import uuid4
from datetime import datetime,timedelta,timezone
from app.auth import mint_telegram_session
from app.db import SessionLocal
from app.models import User,SubscriptionPlan,LicenseGrant,LicenseEntitlement
import json
raw=mint_telegram_session(1001)
with SessionLocal() as db:
 u=db.query(User).filter_by(telegram_id=1001).one();p=SubscriptionPlan(id=str(uuid4()),request_id=str(uuid4()),created_by=9000,name='test',price_minor=1,currency='EUR',duration_days=30,device_limit=1,platform='hassle',enabled=True);db.add(p)
 g=LicenseGrant(user_id=u.id,key_hash='a'*64,issue_request_id=str(uuid4()),duration_days=30,activated_at=datetime.now(timezone.utc),expires_at=datetime.now(timezone.utc)+timedelta(days=30));db.add(g);db.flush();db.add(LicenseEntitlement(grant_id=g.id,plan_id=p.id,platform='hassle',device_limit=1));db.commit();print(json.dumps({'session':raw,'grant':g.id}))
'''
    seeded=json.loads(subprocess.run([sys.executable,'-c',seed],cwd=ROOT,env=env,check=True,capture_output=True,text=True).stdout)
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port),'--log-level','error','--no-access-log'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=3) as c:
            for _ in range(100):
                if proc.poll() is not None:raise RuntimeError('uvicorn failed')
                try:
                    if c.get('/health').status_code==200:break
                except httpx.HTTPError:time.sleep(.05)
            else:raise RuntimeError('uvicorn timeout')
            user={'Authorization':'Bearer '+seeded['session']}
            r=c.post('/v2/device/pairings',json={'name':'network test','platform':'hassle_rp_2'});assert r.status_code==201;p=r.json()
            assert c.post('/v2/pairings/preview',headers=user,json={'pairing_code':p['pairing_code']}).status_code==200
            assert c.post('/v2/pairings/confirm',headers=user,json={'pairing_id':p['pairing_id'],'pairing_code':p['pairing_code'],'license_id':seeded['grant']}).status_code==200
            r=c.post('/v2/device/pairings/claim',json={'pairing_id':p['pairing_id'],'claim_secret':p['claim_secret']});assert r.status_code==200;d=r.json();assert d['device_id']==p['device_id']
            dev={'Authorization':'Bearer '+d['device_credential']};assert c.get('/v2/device/access',headers=dev).json()['status']=='active'
            assert c.post('/v2/devices/'+d['device_id']+'/revoke',headers=user).status_code==200
            assert c.get('/v2/device/access',headers=dev).status_code==401
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
