"""Independent event queue worker; sends metadata-only Telegram notifications."""
from datetime import timedelta
from sqlalchemy import update
from app.db import SessionLocal
from app.models import User,Device,LicenseGrant,NotificationSetting
from app.v2.models import GameEvent,GameEventJob
from app.v2.security import now,evaluate
import secrets

def claim_one():
    with SessionLocal() as db:
        t=now()
        db.execute(update(GameEventJob).where(GameEventJob.status=='processing',GameEventJob.lease_until<=t,GameEventJob.attempts>=5).values(status='failed',error_code='lease_exhausted',lease_token=None,lease_until=None))
        db.execute(update(GameEventJob).where(GameEventJob.status=='processing',GameEventJob.lease_until<=t,GameEventJob.attempts<5).values(status='pending',lease_token=None,lease_until=None,next_attempt_at=t))
        db.commit()
        job=db.query(GameEventJob).filter(GameEventJob.status=='pending',GameEventJob.next_attempt_at<=t).order_by(GameEventJob.next_attempt_at).first()
        if not job:return None
        token=secrets.token_hex(24)
        changed=db.execute(update(GameEventJob).where(GameEventJob.id==job.id,GameEventJob.status=='pending',GameEventJob.next_attempt_at<=t).values(status='processing',attempts=GameEventJob.attempts+1,lease_until=t+timedelta(seconds=120),lease_token=token).execution_options(synchronize_session=False))
        db.commit()
        if not changed.rowcount:return None
        db.refresh(job);event=db.get(GameEvent,job.event_id);u=db.get(User,job.user_id);d=db.get(Device,event.device_id) if event else None
        _,reason=evaluate(db,db.get(LicenseGrant,d.license_id),d) if d else (None,'DEVICE_UNAVAILABLE')
        opted=db.query(NotificationSetting).filter_by(user_id=job.user_id,platform=d.platform,kind=event.event_type,enabled=True).first() if event and d else None
        if not u or reason or not opted:
            job.status='cancelled';job.error_code='not_available_or_opted_out';job.lease_until=None;job.lease_token=None;db.commit();return None
        return {'id':job.id,'token':token,'attempts':job.attempts,'telegram_id':u.telegram_id}

def finish(job,status,error=None,delay=0):
    with SessionLocal() as db:
        values={'status':status,'error_code':error,'lease_until':None,'lease_token':None}
        if status=='sent':values['sent_at']=now()
        if status=='pending':values['next_attempt_at']=now()+timedelta(seconds=delay)
        r=db.execute(update(GameEventJob).where(GameEventJob.id==job['id'],GameEventJob.status=='processing',GameEventJob.lease_token==job['token']).values(**values));db.commit();return bool(r.rowcount)

async def process_one(bot):
    from aiogram.exceptions import TelegramRetryAfter,TelegramForbiddenError,TelegramBadRequest,TelegramUnauthorizedError
    job=claim_one()
    if not job:return False
    try:
        await bot.send_message(job['telegram_id'],'🎮 NØRI: получено событие устройства. Проверьте статус подключения.')
    except (TelegramForbiddenError,TelegramBadRequest,TelegramUnauthorizedError):finish(job,'failed','telegram_permanent')
    except Exception as exc:
        if job['attempts']>=5:finish(job,'failed','attempts_exhausted')
        else:finish(job,'pending','temporary_error',max(1,min(3600,exc.retry_after)) if isinstance(exc,TelegramRetryAfter) else min(300,10*2**(job['attempts']-1)))
    else:finish(job,'sent')
    return True
