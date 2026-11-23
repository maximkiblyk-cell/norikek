"""Experimental, test-only device pairing. No game process or SDK access here."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID
import hashlib
import hmac
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db import get_db
from app.models import User, LicenseGrant, Device, DevicePairing, LicenseEntitlement, AccountAccess

router = APIRouter()

def enabled():
    # v1 pairing allowed unconfirmed entitlement snapshots; retire rather than bypass v2.
    raise HTTPException(503, "Legacy device pairing disabled; use v2")

def timestamp(): return datetime.now(timezone.utc)
def aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def digest(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()

class PairStart(BaseModel):
    platform: Literal['hassle','radmir']
    name: str = Field(min_length=1, max_length=80)

class PairClaim(BaseModel):
    pairing_id: UUID
    claim_secret: str = Field(min_length=32,max_length=100)

class Confirm(BaseModel):
    code: str = Field(min_length=16,max_length=16,pattern=r'^[A-Z2-7]+$')
    telegram_id: int = Field(gt=0)

@router.post('/v1/device/pairing/start', dependencies=[Depends(enabled)])
def start(body: PairStart, db: Session = Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(422, 'Device name required')
    alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
    code=''.join(secrets.choice(alphabet) for _ in range(16))
    claim_secret=secrets.token_urlsafe(32)
    entry=DevicePairing(id=str(uuid4()), code_hash=digest(code), claim_hash=digest(claim_secret),
                        platform=body.platform, name=body.name.strip(),
                        expires_at=timestamp()+timedelta(seconds=settings.pairing_ttl_seconds))
    db.add(entry); db.commit()
    return {'pairing_id':entry.id, 'code':code, 'claim_secret':claim_secret, 'expires_in':settings.pairing_ttl_seconds}

def confirm(body: Confirm, db: Session):
    enabled()
    user=db.query(User).filter_by(telegram_id=body.telegram_id).with_for_update().first()
    if user is None:
        raise HTTPException(404, 'User not registered')
    pair=db.query(DevicePairing).filter_by(code_hash=digest(body.code)).with_for_update().first()
    if pair is None or pair.confirmed_at or aware(pair.expires_at)<=timestamp():
        raise HTTPException(400, 'Invalid or expired code')
    grants=db.query(LicenseGrant).filter(LicenseGrant.user_id==user.id, LicenseGrant.activated_at.is_not(None),
        LicenseGrant.revoked_at.is_(None), LicenseGrant.expires_at>timestamp()).order_by(LicenseGrant.expires_at.desc()).all()
    if not grants: raise HTTPException(403, 'Active license required')
    # User row lock serializes all grant limit checks on PostgreSQL.
    db.execute(update(Device).where(Device.user_id==user.id,Device.status=='pending',Device.pending_expires_at<=timestamp()).values(status='expired').execution_options(synchronize_session=False))
    grant=None
    for candidate in grants:
        entitlement=db.get(LicenseEntitlement,candidate.id)
        allowed_platform=entitlement.platform if entitlement else 'both'
        if allowed_platform not in ('both',pair.platform): continue
        limit=entitlement.device_limit if entitlement else settings.device_limit
        count=db.query(Device).filter(Device.license_id==candidate.id,Device.status.in_(['pending','active'])).count()
        if count < limit:
            grant=candidate
            break
    if grant is None: raise HTTPException(409,'No license with available device slot for platform')
    device=Device(id=str(uuid4()),user_id=user.id,license_id=grant.id,platform=pair.platform,
                  name=pair.name,status='pending',pending_expires_at=pair.expires_at)
    db.add(device); db.flush()
    pair.confirmed_at=timestamp(); pair.device_id=device.id
    db.commit()
    return {'status':'confirmed_awaiting_device_claim','device_id':device.id,'platform':device.platform}

@router.post('/v1/device/pairing/claim', dependencies=[Depends(enabled)])
def claim(body: PairClaim, db: Session = Depends(get_db)):
    pair=db.query(DevicePairing).filter_by(id=str(body.pairing_id)).with_for_update().first()
    if pair is None or not hmac.compare_digest(pair.claim_hash,digest(body.claim_secret)):
        raise HTTPException(400,'Invalid or expired pairing')
    if pair.claimed_at or not pair.confirmed_at or aware(pair.expires_at)<=timestamp() or not pair.device_id:
        raise HTTPException(400,'Invalid or expired pairing')
    device=db.get(Device,pair.device_id); grant=db.get(LicenseGrant,device.license_id) if device else None
    access=db.get(AccountAccess,device.user_id) if device else None
    entitlement=db.get(LicenseEntitlement,device.license_id) if device else None
    if not device or device.status!='pending' or not grant or grant.revoked_at or not grant.activated_at or not grant.expires_at or aware(grant.expires_at)<=timestamp() or (access and access.disabled) or (entitlement and entitlement.platform not in ('both',device.platform)):
        raise HTTPException(403,'Device or license unavailable')
    token=secrets.token_urlsafe(32)
    # Compare-and-swap also prevents reuse in SQLite; transaction rolls back on error.
    updated=db.execute(update(DevicePairing).where(DevicePairing.id==pair.id,DevicePairing.claimed_at.is_(None)).values(claimed_at=timestamp()).execution_options(synchronize_session=False))
    if not updated.rowcount:
        db.rollback(); raise HTTPException(400,'Invalid or expired pairing')
    result=db.execute(update(Device).where(Device.id==device.id,Device.status=='pending').values(status='active',credential_hash=digest(token),pending_expires_at=None).execution_options(synchronize_session=False))
    if not result.rowcount:
        db.rollback(); raise HTTPException(409,'Device unavailable')
    db.commit()
    # One-time response. On lost response, revoke and repeat pairing; token cannot be recovered.
    return {'device_id':device.id,'device_token':token,'status':'active'}

def authenticate_device(authorization: str|None=Header(default=None), db: Session=Depends(get_db)):
    enabled()
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Invalid device credentials')
    credential=authorization[7:]
    if len(credential)<32 or len(credential)>100:
        raise HTTPException(401,'Invalid device credentials')
    device=db.query(Device).filter_by(credential_hash=digest(credential),status='active').first()
    if not device:
        raise HTTPException(401,'Invalid device credentials')
    grant=db.get(LicenseGrant,device.license_id)
    access=db.get(AccountAccess,device.user_id)
    entitlement=db.get(LicenseEntitlement,device.license_id)
    if (not grant or grant.user_id!=device.user_id or grant.revoked_at or not grant.activated_at or not grant.expires_at
        or aware(grant.expires_at)<=timestamp() or (access and access.disabled)
        or (entitlement and entitlement.platform not in ('both',device.platform))):
        raise HTTPException(403,'License unavailable')
    return device

@router.get('/v1/device/me')
def device_me(device: Device=Depends(authenticate_device), db: Session=Depends(get_db)):
    device.last_seen_at=timestamp(); db.commit()
    return {'device_id':device.id,'platform':device.platform,'status':device.status}

def public_device(device):
    return {'id':device.id,'name':device.name,'platform':device.platform,'status':device.status,
            'created_at':device.created_at,'last_seen_at':device.last_seen_at,'revoked_at':device.revoked_at}

def list_for_user(telegram_id:int,db:Session):
    user=db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user: raise HTTPException(404,'User not registered')
    return {'devices':[public_device(d) for d in db.query(Device).filter_by(user_id=user.id).order_by(Device.created_at.desc()).limit(100).all()]}

def revoke_for_user(telegram_id:int,device_id:str,db:Session):
    user=db.query(User).filter_by(telegram_id=telegram_id).first()
    device=db.query(Device).filter_by(id=device_id,user_id=user.id).first() if user else None
    if not device: raise HTTPException(404,'Device not found')
    if device.status!='revoked':
        device.status='revoked'; device.revoked_at=timestamp(); device.credential_hash=None
        db.commit()
    return public_device(device)
