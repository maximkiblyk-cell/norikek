"""Destructive stop/restart ONLY of a brand-new TemporaryDirectory PostgreSQL cluster.
Requires initdb/pg_ctl on PATH, backend Python deps and libpq; never targets a supplied cluster.
"""
import os,pathlib,socket,subprocess,sys,tempfile,time,urllib.error,urllib.request

def freeport():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def status(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/ready',timeout=2) as r:return r.status
    except urllib.error.HTTPError as e:return e.code

def pg(action,data,log,sock,port):
    cmd=['pg_ctl','-D',str(data)]
    if action=='start':cmd+=['-l',str(log),'-o',f'-k {sock} -p {port} -c listen_addresses=', 'start']
    else:cmd+=['stop','-m','fast']
    subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

with tempfile.TemporaryDirectory(prefix='nori-v083-postgres-recovery-') as tmp:
    t=pathlib.Path(tmp);data=t/'pg';sock=t/'sock';sock.mkdir();log=t/'pg.log';pgport=freeport();apiport=freeport()
    subprocess.run(['initdb','-D',str(data),'-U','nori_test','--auth=trust','--no-locale','--encoding=UTF8'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    proc=None;started=False
    try:
        pg('start',data,log,sock,pgport);started=True
        env={**os.environ,'DATABASE_URL':f'postgresql+psycopg://nori_test@/postgres?host={sock}&port={pgport}','AUTO_CREATE_SCHEMA':'false','BOT_TOKEN':''}
        root=pathlib.Path(__file__).resolve().parents[1]
        proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(apiport),'--no-access-log','--log-level','error'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            if proc.poll() is not None:raise RuntimeError('API startup failed')
            try:
                if status(apiport)==200:break
            except OSError:pass
            time.sleep(.1)
        else:raise RuntimeError('API did not become ready')
        pg('stop',data,log,sock,pgport);started=False
        assert status(apiport)==503,'unavailable PostgreSQL must return 503'
        pg('start',data,log,sock,pgport);started=True
        assert status(apiport)==200,'ready failed after database returns'
        # Warm the pool and restart without an intervening application request.
        assert status(apiport)==200
        pg('stop',data,log,sock,pgport);started=False
        pg('start',data,log,sock,pgport);started=True
        assert status(apiport)==200,'first request used a stale pooled connection'
        print('PASS PostgreSQL temporary cluster: ready=200, stopped=503, recovered=200, first request after silent restart=200 (pool pre-ping)')
    finally:
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=5)
        if started:pg('stop',data,log,sock,pgport)
