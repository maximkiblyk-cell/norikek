"""Real Telegram worker for persisted support replies. Local-dev, not production-hardened."""
import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import update
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest, TelegramUnauthorizedError
from app.core.config import settings
from app.db import Base, engine, SessionLocal
from app.models import NotificationJob, NotificationSetting, User, SystemError

log = logging.getLogger("nori.worker")
MAX_ATTEMPTS = 5
LEASE_SECONDS = 120
POLL_SECONDS = 2

def now():
    return datetime.now(timezone.utc)

def claim_one():
    """Optimistic claim; expired leases may be retried, so delivery is at-least-once."""
    with SessionLocal() as db:
        moment = now()
        # Mark exhausted leases terminal; otherwise an abandoned processing job can retry.
        db.execute(update(NotificationJob).where(NotificationJob.status == "processing", NotificationJob.lease_until <= moment,
                                                  NotificationJob.attempts >= MAX_ATTEMPTS)
                   .values(status="exhausted", lease_token=None, lease_until=None, error_code="lease_expired"))
        db.execute(update(NotificationJob).where(NotificationJob.status == "processing", NotificationJob.lease_until <= moment,
                                                  NotificationJob.attempts < MAX_ATTEMPTS)
                   .values(status="pending", lease_token=None, lease_until=None, next_attempt_at=moment, error_code="lease_expired"))
        db.commit()
        job = db.query(NotificationJob).filter(NotificationJob.status == "pending", NotificationJob.next_attempt_at <= moment).order_by(NotificationJob.id).first()
        if not job:
            return None
        token = secrets.token_hex(24)
        result = db.execute(update(NotificationJob).where(NotificationJob.id == job.id, NotificationJob.status == "pending", NotificationJob.next_attempt_at <= moment)
            .values(status="processing", lease_token=token, lease_until=moment + timedelta(seconds=LEASE_SECONDS), attempts=NotificationJob.attempts+1).execution_options(synchronize_session=False))
        db.commit()
        if not result.rowcount:
            return None
        db.refresh(job)
        user = db.get(User, job.user_id)
        if not user:
            # Foreign-key integrity isn't guaranteed in SQLite; fail closed.
            job.status = "failed"; job.error_code = "user_missing"; job.lease_token = None; job.lease_until = None
            db.commit(); return None
        opt_in = db.query(NotificationSetting).filter_by(user_id=user.id, kind="system", enabled=True).first()
        if not opt_in:
            job.status = "cancelled"; job.error_code = "notifications_disabled"; job.lease_token = None; job.lease_until = None
            db.commit(); return None
        return {"id":job.id,"ticket_id":job.ticket_id,"telegram_id":user.telegram_id,"token":token,"attempts":job.attempts}

def finish(job, status, error_code=None, telegram_message_id=None, delay_seconds=0):
    with SessionLocal() as db:
        values = {"status": status, "lease_token": None, "lease_until": None, "error_code": error_code}
        if status == "sent":
            values.update(sent_at=now(), telegram_message_id=telegram_message_id)
        if status == "pending":
            values["next_attempt_at"] = now()+timedelta(seconds=delay_seconds)
        result = db.execute(update(NotificationJob).where(NotificationJob.id == job['id'], NotificationJob.status == "processing", NotificationJob.lease_token == job['token']).values(**values))
        if result.rowcount and status in {"failed", "exhausted"}:
            db.add(SystemError(component="telegram_worker", code=error_code or status, job_id=job['id']))
        db.commit()
        return bool(result.rowcount)

async def process_one(bot):
    job = claim_one()
    if not job:
        return False
    try:
        msg = await bot.send_message(job['telegram_id'], f"🛟 NØRI: новый ответ поддержки по обращению №{job['ticket_id']}. Откройте бота → Поддержка → Мои обращения.")
    except (TelegramForbiddenError, TelegramBadRequest, TelegramUnauthorizedError):
        finish(job, "failed", "telegram_permanent")
    except Exception as exc:
        if job['attempts'] >= MAX_ATTEMPTS:
            finish(job, "exhausted", "temporary_error")
        else:
            delay = max(1, min(3600, exc.retry_after)) if isinstance(exc, TelegramRetryAfter) else min(300, 10 * (2 ** (job['attempts'] - 1)))
            finish(job, "pending", "temporary_error", delay_seconds=delay)
    else:
        # Telegram API accepted the message; this does not prove the recipient read it.
        if not finish(job, "sent", telegram_message_id=msg.message_id):
            log.warning("Lease lost after Telegram accepted notification; duplicate delivery is possible")
    return True

async def main():
    if not settings.bot_token:
        raise RuntimeError("Set a TEST BOT_TOKEN in .env")
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    bot = Bot(settings.bot_token)
    try:
        while True:
            try:
                processed = await process_one(bot)
                from app.v2.event_worker import process_one as process_game_event
                processed = (await process_game_event(bot)) or processed
            except Exception:
                # Do not log SQL parameters or secrets; retry transient DB failures.
                log.error("Worker iteration failed; retrying")
                await asyncio.sleep(5)
                continue
            if not processed:
                await asyncio.sleep(POLL_SECONDS)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
