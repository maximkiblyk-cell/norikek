"""Integration: local TLS gateway -> v0.8 FastAPI. No production data."""
import http.server, os, pathlib, socket, ssl, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request

def freeport():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));return s.getsockname()[1]

with tempfile.TemporaryDirectory(prefix='nori-tls-test-') as d:
    root=pathlib.Path(__file__).resolve().parents[2];backend=freeport();port=freeport()
    cert=pathlib.Path(d)/'cert.pem';key=pathlib.Path(d)/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    env=os.environ.copy();env['DATABASE_URL']='sqlite:///'+d+'/test.db';env['AUTO_CREATE_SCHEMA']='true';env['BOT_TOKEN']='';env.pop('SERVICE_TOKEN',None)
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(backend),'--log-level','error'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/slow':time.sleep(3);self.send_response(200);self.end_headers();return
            try:
                r=urllib.request.urlopen('http://127.0.0.1:'+str(backend)+self.path,timeout=2);body=r.read();status=r.status
            except urllib.error.HTTPError as e:body=e.read();status=e.code
            except Exception:self.send_error(502);return
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers()
            try:self.wfile.write(body)
            except OSError:pass
    class Server(http.server.ThreadingHTTPServer):
        daemon_threads=True
        def handle_error(self, request, client_address):
            # Certificate rejection intentionally resets the test connection.
            pass
    try:
        for _ in range(100):
            if proc.poll() is not None:raise RuntimeError('Backend failed to start')
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(backend)+'/health',timeout=.2):break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Backend not ready')
        server=Server(('127.0.0.1',port),Handler);ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key);server.socket=ctx.wrap_socket(server.socket,server_side=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        subprocess.run([sys.argv[1],f'https://localhost:{port}',str(cert)],check=True)
        server.shutdown();server.server_close()
    finally:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
