"""Isolated HTTPS gateway, actual v2 API and C++ client; Telegram confirmation is test-driven."""
import http.server,json,os,pathlib,socket,ssl,subprocess,sys,tempfile,threading,time,urllib.error,urllib.request
from datetime import datetime,timedelta,timezone
from contextlib import closing

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def call(url,method='GET',data=None,token=None):
    body=json.dumps(data).encode() if data is not None else None;headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers,method=method),timeout=4) as r:return json.load(r)
with tempfile.TemporaryDirectory(prefix='nori-v081-flow-') as d:
    root=pathlib.Path(__file__).resolve().parents[2]; backend=port();tls=port();db=pathlib.Path(d)/'db.sqlite';cert=pathlib.Path(d)/'cert.pem';key=pathlib.Path(d)/'key.pem'
    cert_result=subprocess.run([os.environ.get('NORI_TEST_OPENSSL','openssl'),'req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',str(key),'-out',str(cert)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    if cert_result.returncode:raise RuntimeError('OpenSSL certificate generation failed: '+cert_result.stderr)
    env={**os.environ,'DATABASE_URL':'sqlite:///'+db.as_posix(),'AUTO_CREATE_SCHEMA':'false','BOT_TOKEN':''}
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,check=True)
    seed='''
from uuid import uuid4
from datetime import datetime,timedelta,timezone
from contextlib import closing
from app.auth import mint_telegram_session
from app.db import SessionLocal
from app.models import User,SubscriptionPlan,LicenseGrant,LicenseEntitlement
import json
session=mint_telegram_session(1001)
with SessionLocal() as db:
 u=db.query(User).filter_by(telegram_id=1001).one();p=SubscriptionPlan(id=str(uuid4()),request_id=str(uuid4()),created_by=1,name='p',price_minor=1,currency='EUR',duration_days=30,device_limit=1,platform='hassle',enabled=True);db.add(p)
 g=LicenseGrant(user_id=u.id,key_hash='a'*64,issue_request_id=str(uuid4()),duration_days=30,activated_at=datetime.now(timezone.utc)-timedelta(days=1),expires_at=datetime.now(timezone.utc)+timedelta(days=30));db.add(g);db.flush();db.add(LicenseEntitlement(grant_id=g.id,plan_id=p.id,platform='hassle',device_limit=1));db.commit();print(json.dumps({'session':session,'grant':g.id}))
'''
    seed_result=subprocess.run([sys.executable,'-c',seed],cwd=root,env=env,capture_output=True,text=True)
    if seed_result.returncode:raise RuntimeError('Test data setup failed: '+seed_result.stderr)
    seeded=json.loads(seed_result.stdout)
    backend_log=tempfile.TemporaryFile(mode='w+t',encoding='utf-8')
    api=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(backend),'--no-access-log','--log-level','error'],cwd=root,env=env,stdout=backend_log,stderr=backend_log)
    down=threading.Event()
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):self.forward()
        def do_POST(self):self.forward()
        def forward(self):
            if down.is_set():self.send_error(503);return
            body=self.rfile.read(int(self.headers.get('Content-Length','0'))) if self.command=='POST' else None
            headers={k:v for k,v in self.headers.items() if k.lower() in ('authorization','content-type')}
            req=urllib.request.Request(f'http://127.0.0.1:{backend}'+self.path,data=body,headers=headers,method=self.command)
            try:
                with urllib.request.urlopen(req,timeout=3) as r:payload=r.read();status=r.status
            except urllib.error.HTTPError as e:payload=e.read();status=e.code
            except Exception:self.send_error(502);return
            self.send_response(status);self.send_header('Content-Length',str(len(payload)));self.send_header('Content-Type','application/json');self.end_headers()
            try:self.wfile.write(payload)
            except OSError:pass
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads=True
        def handle_error(self,*args):pass
    server=None;client=None
    try:
        for _ in range(100):
            if api.poll() is not None:raise RuntimeError('API startup failed')
            try:call(f'http://127.0.0.1:{backend}/health');break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('API not ready')
        server=Server(('127.0.0.1',tls),H);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key);server.socket=ctx.wrap_socket(server.socket,server_side=True);threading.Thread(target=server.serve_forever,daemon=True).start()
        client=subprocess.Popen([sys.argv[1],f'https://localhost:{tls}',str(cert)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        line=client.stdout.readline().strip();assert line.startswith('CODE '),line
        code=line[5:];base=f'http://127.0.0.1:{backend}';u=seeded['session'];p=call(base+'/v2/pairings/preview','POST',{'pairing_code':code},u);call(base+'/v2/pairings/confirm','POST',{'pairing_id':p['pairing_id'],'pairing_code':code,'license_id':seeded['grant']},u)
        def step(expected):
            client.stdin.write('next\n');client.stdin.flush();line=client.stdout.readline().strip()
            if line!=expected:raise RuntimeError('C++ flow failed at '+expected+': '+line+' '+(client.stderr.read() if client.poll() is not None else ''))
        step('ONLINE');down.set();step('OFFLINE');down.clear();step('RECONNECTED')
        import sqlite3
        with closing(sqlite3.connect(db)) as c, c:c.execute('update license_grants set expires_at=? where id=?',((datetime.now(timezone.utc)-timedelta(days=1)).isoformat(),seeded['grant']))
        step('DENIED')
        with closing(sqlite3.connect(db)) as c, c:c.execute('update license_grants set expires_at=? where id=?',((datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),seeded['grant']))
        step('RENEWED')
        with closing(sqlite3.connect(db)) as c:device=c.execute('select id from devices').fetchone()[0]
        call(base+'/v2/devices/'+device+'/revoke','POST',{},u);step('REVOKED');assert client.wait(timeout=5)==0
        print('C++ v2 / TLS / actual backend: pre-confirm, claim, access, outage, reconnect, expiration, renewal, revocation passed; test-only memory vault and test-driven confirmation')
    finally:
        if client and client.poll() is None:client.kill();client.wait()
        if server:server.shutdown();server.server_close()
        api.terminate()
        try:api.wait(timeout=5)
        except subprocess.TimeoutExpired:api.kill();api.wait()
        if sys.exc_info()[0]:
            backend_log.seek(0);print("Backend test log:\n"+backend_log.read(),file=sys.stderr)
        backend_log.close()
