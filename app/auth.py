"""Identity boundary: only Telegram ingress can issue short-lived user sessions.

The bot is part of the trusted backend and has DB write privileges. Compromise of
bot token, bot process, DB or owner configuration still compromises identities.
No HTTP endpoint accepts arbitrary Telegram identity assertions.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db import get_db, SessionLocal
from app.models import User, AuthSession, AccountAccess

@dataclass(frozen=True)
class Principal:
    telegram_id: int
    user_id: int
    role: str

current_principal: ContextVar[Principal | None] = ContextVar('current_principal', default=None)
bot_session: ContextVar[str | None] = ContextVar('bot_session', default=None)

def digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def owner_ids():
    return {int(x.strip()) for x in settings.owner_telegram_ids.split(',') if x.strip().isdigit() and int(x.strip()) > 0}

def role_for(user, access):
    if user.telegram_id in owner_ids():
        return 'owner'
    return access.role if access and access.role in {'user','admin'} else 'user'

def mint_telegram_session(telegram_id: int, username: str | None = None) -> str:
    """Call only from trusted Telegram polling ingress; never expose as an API."""
    if telegram_id <= 0: raise ValueError('Invalid Telegram identity')
    with SessionLocal() as db:
        user = db.query(User).filter_by(telegram_id=telegram_id).first()
        if user is None:
            user=User(telegram_id=telegram_id, username=username)
            db.add(user)
            try: db.commit()
            except IntegrityError: db.rollback()
            user=db.query(User).filter_by(telegram_id=telegram_id).one()
        access=db.get(AccountAccess,user.id)
        if access and access.disabled:
            raise PermissionError('Account disabled')
        raw=secrets.token_urlsafe(32)
        db.add(AuthSession(token_hash=digest(raw),user_id=user.id,expires_at=datetime.now(timezone.utc)+timedelta(minutes=5)))
        db.commit()
        return raw

def revoke_session(raw: str):
    with SessionLocal() as db:
        db.query(AuthSession).filter_by(token_hash=digest(raw)).delete()
        # Opportunistic cleanup bounds expired session accumulation after crashes.
        db.query(AuthSession).filter(AuthSession.expires_at < datetime.now(timezone.utc)).delete()
        db.commit()

async def require_identity(request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'User session required')
    raw=authorization[7:]
    if len(raw)<32 or len(raw)>100:
        raise HTTPException(401,'Invalid user session')
    session=db.get(AuthSession,digest(raw))
    if not session or utc(session.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(401,'Invalid or expired user session')
    user=db.get(User,session.user_id)
    access=db.get(AccountAccess,user.id) if user else None
    if not user or (access and access.disabled):
        raise HTTPException(403,'Account unavailable')
    principal=Principal(user.telegram_id,user.id,role_for(user,access))
    path=request.url.path
    if path.startswith('/v1/admin/') and principal.role not in {'admin','owner'}:
        raise HTTPException(403,'Administrator access denied')
    m=re.match(r'^/v1/users/(\d+)(?:/|$)',path)
    if m and int(m.group(1)) != principal.telegram_id:
        raise HTTPException(403,'User identity mismatch')
    supplied=[]
    if 'actor_telegram_id' in request.query_params:
        supplied.append(request.query_params['actor_telegram_id'])
    if request.method in {'POST','PUT','PATCH'}:
        try: data=await request.json()
        except (ValueError,UnicodeDecodeError): data={}
        if isinstance(data,dict):
            if 'actor_telegram_id' in data: supplied.append(data['actor_telegram_id'])
            if path in {'/v1/users','/v1/pairing/confirm','/v1/payments'} and 'telegram_id' in data:
                supplied.append(data['telegram_id'])
    if any(str(x) != str(principal.telegram_id) for x in supplied):
        raise HTTPException(403,'User identity mismatch')
    request.state.principal=principal
    context_token=current_principal.set(principal)
    try: yield principal
    finally: current_principal.reset(context_token)
