from app.bot.main import main_keyboard, KINDS

def test_menu_uses_only_inline_buttons():
    menu = main_keyboard()
    actions = [button.callback_data for row in menu.inline_keyboard for button in row]
    assert len(actions) == len(set(actions))
    assert {"connect", "account", "support", "notifications"} <= set(actions)

def test_notification_kinds_are_defined():
    assert set(KINDS) == {"sms", "calls", "ads", "queue", "system"}

def test_bot_start_and_license_conversation_without_telegram_network(monkeypatch):
    import asyncio
    import time
    from aiogram import Bot
    from aiogram.types import Update
    from aiogram.client.session.base import BaseSession
    import app.bot.main as mod

    class FakeSession(BaseSession):
        def __init__(self):
            super().__init__()
            self.methods=[]
        async def close(self):
            pass
        async def make_request(self, bot, method, timeout=None):
            self.methods.append(type(method).__name__)
            return True
        async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
            if False:
                yield b''

    calls=[]
    async def fake_api(method, path, body=None):
        calls.append((method,path,body))
        if path.endswith('/licenses/activate'):
            return {'id':12,'status':'active','expires_at':'2026-12-23T00:00:00+00:00'}
        return {'user_id':1}
    monkeypatch.setattr(mod, 'api', fake_api)
    monkeypatch.setattr(mod, 'mint_telegram_session', lambda *args: 'isolated-fake-session')
    monkeypatch.setattr(mod, 'revoke_session', lambda *args: None)
    now=int(time.time())
    user={'id':424242, 'is_bot':False,'first_name':'Test'}
    chat={'id':424242,'type':'private'}
    async def run():
        session=FakeSession()
        bot=Bot('123456:abcdefghijklmnopqrstuvwxyzABCDE12345678',session=session)
        start=Update.model_validate({'update_id':1,'message':{'message_id':1,'date':now,'chat':chat,'from':user,'text':'/start','entities':[{'type':'bot_command','offset':0,'length':6}]}})
        await mod.dp.feed_update(bot,start)
        callback=Update.model_validate({'update_id':2,'callback_query':{'id':'cb1','from':user,'chat_instance':'x','data':'license_activate','message':{'message_id':2,'date':now,'chat':chat,'from':{'id':123456,'is_bot':True,'first_name':'Bot'}}}})
        await mod.dp.feed_update(bot,callback)
        key=Update.model_validate({'update_id':3,'message':{'message_id':3,'date':now,'chat':chat,'from':user,'text':'NORI-test-key-123456789'}})
        await mod.dp.feed_update(bot,key)
        assert ('POST','/v1/users',{'telegram_id':424242,'username':None}) in calls
        assert any(path == '/v1/users/424242/licenses/activate' for _,path,_ in calls)
        assert 'DeleteMessage' in session.methods and 'AnswerCallbackQuery' in session.methods
        await bot.session.close()
    asyncio.run(run())

def test_v2_pairing_bot_preview_then_confirmation_without_telegram_network(monkeypatch):
    """Fake Telegram transport and API: tests bot FSM only, not a live bot."""
    import asyncio,time
    from aiogram import Bot
    from aiogram.types import Update
    from aiogram.client.session.base import BaseSession
    import app.bot.main as mod
    calls=[]
    class FakeSession(BaseSession):
        def __init__(self):super().__init__();self.methods=[]
        async def close(self):pass
        async def make_request(self,bot,method,timeout=None):self.methods.append(type(method).__name__);return True
        async def stream_content(self,url,headers=None,timeout=30,chunk_size=65536,raise_for_status=True):
            if False:yield b''
    async def fake_api(method,path,body=None):
        calls.append((method,path,body))
        if path=='/v2/pairings/preview':return {'pairing_id':'pair-id','name':'Test PC','platform':'hassle_rp_2','device_id_suffix':'1234'}
        if path.endswith('/licenses'):return {'licenses':[{'id':7,'status':'active','access':{'allowed':True},'entitlement':{'plan_id':'plan','platform':'hassle'}}]}
        return {'status':'confirmed'}
    monkeypatch.setattr(mod,'api',fake_api);monkeypatch.setattr(mod,'mint_telegram_session',lambda *args:'test-session');monkeypatch.setattr(mod,'revoke_session',lambda *args:None)
    user={'id':434343,'is_bot':False,'first_name':'Test'};chat={'id':434343,'type':'private'};ts=int(time.time())
    def callback(i,data):return Update.model_validate({'update_id':i,'callback_query':{'id':f'cb{i}','from':user,'chat_instance':'x','data':data,'message':{'message_id':i,'date':ts,'chat':chat,'from':{'id':123456,'is_bot':True,'first_name':'Bot'}}}})
    async def run():
        transport=FakeSession();bot=Bot('123456:abcdefghijklmnopqrstuvwxyzABCDE12345678',session=transport)
        await mod.dp.feed_update(bot,callback(1,'pair_enter'))
        await mod.dp.feed_update(bot,Update.model_validate({'update_id':2,'message':{'message_id':2,'date':ts,'chat':chat,'from':user,'text':'ABCDEFGHIJKLMNOP'}}))
        assert any(p=='/v2/pairings/preview' for _,p,_ in calls)
        assert not any(p=='/v2/pairings/confirm' for _,p,_ in calls)
        await mod.dp.feed_update(bot,callback(3,'pairconfirm:7'))
        assert any(p=='/v2/pairings/confirm' and body['license_id']==7 for _,p,body in calls)
        await bot.session.close()
    asyncio.run(run())
