"""Real local HTTP API + bot dispatcher; Telegram transport is fake, not a live test."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def test_bot_real_http_bridge_and_session_cleanup(tmp_path):
    db=tmp_path/'bot.db'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=os.environ.copy()
    env.update(DATABASE_URL='sqlite:///'+str(db),AUTO_CREATE_SCHEMA='false',OWNER_TELEGRAM_IDS='9000',API_BASE_URL=f'http://127.0.0.1:{port}',BOT_TOKEN='')
    migration=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=env,capture_output=True,text=True)
    assert migration.returncode==0,migration.stderr
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if proc.poll() is not None: raise AssertionError('API process exited')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/ready',timeout=.3) as resp:
                    if resp.status==200: break
            except OSError: time.sleep(.05)
        else: raise AssertionError('API startup timeout')
        script=r'''
import asyncio,time,sqlite3
from aiogram import Bot
from aiogram.types import Update
from aiogram.client.session.base import BaseSession
from app.bot.main import dp
from app.core.config import settings
class FakeSession(BaseSession):
 def __init__(self): super().__init__(); self.methods=[]
 async def close(self): pass
 async def make_request(self,bot,method,timeout=None): self.methods.append(method); return True
 async def stream_content(self,*args,**kwargs):
  if False: yield b''
now=int(time.time())
def msg(seq,uid,text):
 item={'message_id':seq,'date':now,'chat':{'id':uid,'type':'private'},'from':{'id':uid,'is_bot':False,'first_name':'Test'},'text':text}
 if text.startswith('/'):item['entities']=[{'type':'bot_command','offset':0,'length':len(text.split()[0])}]
 return Update.model_validate({'update_id':seq,'message':item})
def cb(seq,uid,data):
 return Update.model_validate({'update_id':seq,'callback_query':{'id':str(seq),'from':{'id':uid,'is_bot':False,'first_name':'Test'},'chat_instance':str(uid),'data':data,'message':{'message_id':seq,'date':now,'chat':{'id':uid,'type':'private'},'from':{'id':123456,'is_bot':True,'first_name':'Bot'}}}})
async def run():
 session=FakeSession(); bot=Bot('123456:abcdefghijklmnopqrstuvwxyzABCDE12345678',session=session)
 for u in [msg(1,1001,'/start'),msg(2,9000,'/start'),msg(3,9000,'/admin'),cb(4,9000,'admin_users'),cb(5,9000,'au:1001'),cb(6,9000,'ausa:1001:1'),cb(7,9000,'aus:1001:1')]: await dp.feed_update(bot,u)
 texts=[getattr(x,'text','') or '' for x in session.methods]
 assert any('АДМИНИСТРИРОВАНИЕ' in x for x in texts),texts
 assert any('ПОЛЬЗОВАТЕЛИ' in x for x in texts),texts
 assert any('Изменение сохранено' in x for x in texts),texts
 with sqlite3.connect(settings.database_url[len('sqlite:///'):]) as db:
  assert db.execute('select disabled from account_access join users on account_access.user_id=users.id where telegram_id=1001').fetchone()==(1,)
  assert db.execute('select count(*) from auth_sessions').fetchone()==(0,)
 await bot.session.close()
asyncio.run(run())
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,text=True,capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()
