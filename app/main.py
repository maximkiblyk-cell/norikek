"""Local development API. Not production-ready; see docs/STATUS.md."""
from contextlib import asynccontextmanager
import hashlib
from fastapi import FastAPI, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import IntegrityError
from app.db import Base, engine, get_db
from app.models import User, License, NotificationSetting, SupportTicket, SupportTicketRequest
from app.schemas import RegisterUser, PairingCreate, PairingConfirm, SettingUpdate, TicketCreate, Platform, Kind
from app.core.config import settings
from app.game.adapters import adapter_status
from app.licenses import router as license_router
from app.support import router as support_router
from app import devices
from app.payments import router as payments_router
from app.auth import require_identity
from app.admin import router as admin_router
from app.v2.pairing import router as v2_pairing_router
from app.v2.queues import router as v2_queue_router
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)  # dev convenience; deployment uses Alembic
    yield

app = FastAPI(title="NØRI API — development", version="0.8.0", lifespan=lifespan)

@app.middleware("http")
async def v2_no_store(request, call_next):
    response=await call_next(request)
    if request.url.path.startswith('/v2/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(SQLAlchemyError)
async def safe_database_error(request, exc):
    # Do not echo SQL, parameters, raw payloads or credentials in the response.
    return JSONResponse(status_code=503,content={'detail':'Database unavailable'},headers={'Cache-Control':'no-store'})

@app.exception_handler(RequestValidationError)
async def safe_validation(request, exc):
    if request.url.path.startswith('/v2/'):
        return JSONResponse(status_code=422,content={'detail':'Invalid request'},headers={'Cache-Control':'no-store'})
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request,exc)

app.include_router(v2_pairing_router)
app.include_router(v2_queue_router)

# Per-user sessions replace the insecure v0.5 shared service bearer.
require_service = require_identity

def user_for(db: Session, telegram_id: int):
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user:
        raise HTTPException(404, "User not registered")
    return user

@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}

@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable")
    return {"status": "ready"}

@app.post("/v1/users", dependencies=[Depends(require_service)])
def register_user(payload: RegisterUser, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(telegram_id=payload.telegram_id).first()
    if user is None:
        user = User(telegram_id=payload.telegram_id, username=payload.username)
        db.add(user)
    else:
        user.username = payload.username
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "telegram_id": user.telegram_id, "created_at": user.created_at}

@app.get("/v1/users/{telegram_id}", dependencies=[Depends(require_service)])
def account(telegram_id: int, db: Session = Depends(get_db)):
    user = user_for(db, telegram_id)
    from app.models import LicenseGrant
    from app.v2.security import evaluate
    grants = db.query(LicenseGrant).filter_by(user_id=user.id).order_by(LicenseGrant.id.desc()).all()
    license_row = next((g for g in grants if evaluate(db,g,user_id=user.id)[1] is None),None)
    return {"telegram_id": user.telegram_id, "username": user.username, "created_at": user.created_at,
            "license": {"active": True, "expires_at": license_row.expires_at} if license_row else None,
            "devices": None}

@app.post("/v1/pairing", dependencies=[Depends(require_service)])
def create_pairing(payload: PairingCreate):
    # Previous implementation created unauthenticated, plaintext codes without binding a device.
    raise HTTPException(503, "Legacy pairing endpoint disabled; see experimental device pairing endpoints")

@app.post("/v1/pairing/confirm", dependencies=[Depends(require_service), Depends(devices.enabled)])
def confirm_pairing(payload: devices.Confirm, db: Session = Depends(get_db)):
    return devices.confirm(payload, db)

@app.get("/v1/users/{telegram_id}/devices", dependencies=[Depends(require_service)])
def list_devices(telegram_id: int, db: Session = Depends(get_db)):
    return devices.list_for_user(telegram_id, db)

@app.post("/v1/users/{telegram_id}/devices/{device_id}/revoke", dependencies=[Depends(require_service)])
def revoke_device(telegram_id: int, device_id: str, db: Session = Depends(get_db)):
    return devices.revoke_for_user(telegram_id, device_id, db)

@app.get("/v1/game/adapters", dependencies=[Depends(require_service)])
def game_adapters():
    return adapter_status()

@app.get("/v1/users/{telegram_id}/settings", dependencies=[Depends(require_service)])
def get_settings(telegram_id: int, db: Session = Depends(get_db)):
    user = user_for(db, telegram_id)
    rows = db.query(NotificationSetting).filter_by(user_id=user.id).all()
    return {"settings": [{"platform": r.platform, "kind": r.kind, "enabled": r.enabled} for r in rows]}

@app.put("/v1/users/{telegram_id}/settings/{platform}/{kind}", dependencies=[Depends(require_service)])
def set_setting(telegram_id: int, platform: Platform, kind: Kind, body: SettingUpdate, db: Session = Depends(get_db)):
    user = user_for(db, telegram_id)
    row = db.query(NotificationSetting).filter_by(user_id=user.id, platform=platform, kind=kind).first()
    if row is None:
        row = NotificationSetting(user_id=user.id, platform=platform, kind=kind, enabled=body.enabled)
        db.add(row)
    else:
        row.enabled = body.enabled
    db.commit()
    return {"platform": platform, "kind": kind, "enabled": row.enabled}

@app.post("/v1/users/{telegram_id}/tickets", dependencies=[Depends(require_service)], status_code=201)
def create_ticket(telegram_id: int, body: TicketCreate, db: Session = Depends(get_db)):
    user = user_for(db, telegram_id)
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Message cannot be blank")
    request_id = str(body.request_id) if body.request_id else None
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    def replay():
        prior = db.get(SupportTicketRequest, request_id) if request_id else None
        if prior is None:
            return None
        if (prior.user_id, prior.category, prior.message_hash) != (user.id, body.category, digest):
            raise HTTPException(409, "Request ID conflict")
        ticket = db.get(SupportTicket, prior.ticket_id)
        return {"id": ticket.id, "status": ticket.status, "created_at": ticket.created_at, "replayed": True}
    previous = replay()
    if previous:
        return previous
    row = SupportTicket(user_id=user.id, category=body.category, message=message)
    db.add(row)
    try:
        db.flush()
        if request_id:
            db.add(SupportTicketRequest(request_id=request_id, ticket_id=row.id, user_id=user.id, category=body.category, message_hash=digest))
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = replay()
        if previous:
            return previous
        raise HTTPException(409, "Request ID conflict")
    db.refresh(row)
    return {"id": row.id, "status": row.status, "created_at": row.created_at, "replayed": False}

@app.get("/v1/users/{telegram_id}/tickets", dependencies=[Depends(require_service)])
def list_tickets(telegram_id: int, db: Session = Depends(get_db)):
    user = user_for(db, telegram_id)
    rows = db.query(SupportTicket).filter_by(user_id=user.id).order_by(SupportTicket.id.desc()).limit(20).all()
    return {"tickets": [{"id": r.id, "category": r.category, "status": r.status, "created_at": r.created_at} for r in rows]}

# User sessions are verified before entering each legacy router.
app.include_router(license_router, dependencies=[Depends(require_service)])

app.include_router(support_router, dependencies=[Depends(require_service)])

app.include_router(devices.router)

app.include_router(payments_router, dependencies=[Depends(require_service)])

app.include_router(admin_router, dependencies=[Depends(require_identity)])
