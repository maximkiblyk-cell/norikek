"""Local-dev licensing API, called by a trusted bot service, not by game clients."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.models import User, LicenseGrant, AdminAudit, LicenseOperation, SystemError, LicenseEntitlement, SubscriptionPlan
from app.core.config import settings

router = APIRouter()

def _now():
    return datetime.now(timezone.utc)

def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def _admin(actor_id: int):
    from app.auth import current_principal
    principal=current_principal.get()
    if not principal or principal.telegram_id != actor_id or principal.role not in {'admin','owner'}:
        raise HTTPException(403, "Administrator access denied")

def _user(db, telegram_id):
    user = db.query(User).filter_by(telegram_id=telegram_id).first()
    if user is None:
        raise HTTPException(404, "User not registered")
    return user

def _hash(key: str):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def _state(grant):
    if grant.revoked_at is not None:
        return "revoked"
    if grant.activated_at is None:
        return "not_activated"
    if grant.expires_at is None or _utc(grant.expires_at) <= _now():
        return "expired"
    return "active"

def _public(grant):
    return {"id": grant.id, "status": _state(grant),
            "activated_at": _utc(grant.activated_at) if grant.activated_at else None,
            "expires_at": _utc(grant.expires_at) if grant.expires_at else None,
            "revoked_at": _utc(grant.revoked_at) if grant.revoked_at else None}

class Issue(BaseModel):
    request_id: UUID
    actor_telegram_id: int = Field(gt=0)
    target_telegram_id: int = Field(gt=0)
    duration_days: int = Field(ge=1, le=3650)

class Activate(BaseModel):
    key: str = Field(min_length=10, max_length=100)

class AdminAction(BaseModel):
    actor_telegram_id: int = Field(gt=0)

class Extend(AdminAction):
    request_id: UUID
    days: int = Field(ge=1, le=3650)

@router.get("/v1/admin/access")
def check_admin_access(actor_telegram_id: int):
    _admin(actor_telegram_id)
    return {"authorized": True}

@router.post("/v1/admin/licenses", status_code=201)
def issue(body: Issue, db: Session = Depends(get_db)):
    _admin(body.actor_telegram_id)
    user = _user(db, body.target_telegram_id)
    if db.query(LicenseGrant).filter_by(issue_request_id=str(body.request_id)).first():
        raise HTTPException(409, "Issue request already processed; key cannot be recovered")
    key = "NORI-" + secrets.token_urlsafe(32)
    grant = LicenseGrant(user_id=user.id, key_hash=_hash(key), issue_request_id=str(body.request_id), duration_days=body.duration_days)
    db.add(grant)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Issue request already processed; key cannot be recovered")
    db.add(AdminAudit(actor_telegram_id=body.actor_telegram_id, action="license_issue", target_user_id=user.id, grant_id=grant.id))
    db.commit()
    # This response is the only time the raw key is recoverable.
    return {"id": grant.id, "key": key, "target_telegram_id": user.telegram_id, "duration_days": grant.duration_days}

@router.post("/v1/users/{telegram_id}/licenses/activate")
def activate(telegram_id: int, body: Activate, db: Session = Depends(get_db)):
    user = _user(db, telegram_id)
    digest = _hash(body.key.strip())
    grant = db.query(LicenseGrant).filter_by(user_id=user.id, key_hash=digest).first()
    if grant is None or grant.revoked_at is not None:
        raise HTTPException(400, "Invalid or revoked key")
    if grant.activated_at is None:
        now = _now()
        # Conditional update ensures the first activation determines the deadline.
        result = db.execute(update(LicenseGrant).where(
            LicenseGrant.id == grant.id, LicenseGrant.user_id == user.id,
            LicenseGrant.activated_at.is_(None), LicenseGrant.revoked_at.is_(None)
        ).values(activated_at=now, expires_at=now + timedelta(days=grant.duration_days)))
        db.commit()
        db.expire_all()
        grant = db.get(LicenseGrant, grant.id)
        if not result.rowcount and (grant is None or grant.revoked_at is not None):
            raise HTTPException(400, "Invalid or revoked key")
    return _public(grant)

@router.get("/v1/users/{telegram_id}/licenses")
def list_licenses(telegram_id: int, db: Session = Depends(get_db)):
    user = _user(db, telegram_id)
    grants = db.query(LicenseGrant).filter_by(user_id=user.id).order_by(LicenseGrant.id.desc()).limit(50).all()
    result=[]
    for g in grants:
        item=_public(g)
        entitlement=db.get(LicenseEntitlement,g.id)
        from app.v2.security import evaluate
        _,reason=evaluate(db,g,user_id=user.id)
        item['entitlement'] = {'plan_id':entitlement.plan_id,'platform':entitlement.platform,'device_limit':entitlement.device_limit} if entitlement else {'plan_id':None,'platform':None,'device_limit':None,'legacy':True}
        item['access'] = {'allowed':reason is None,'reason':reason}
        result.append(item)
    return {"licenses": result}

@router.post("/v1/admin/licenses/{grant_id}/revoke")
def revoke(grant_id: int, body: AdminAction, db: Session = Depends(get_db)):
    _admin(body.actor_telegram_id)
    grant = db.get(LicenseGrant, grant_id)
    if grant is None:
        raise HTTPException(404, "License not found")
    # Conditional update makes repeated revocations idempotent.
    result = db.execute(update(LicenseGrant).where(LicenseGrant.id == grant_id, LicenseGrant.revoked_at.is_(None)).values(revoked_at=_now()))
    if result.rowcount:
        db.add(AdminAudit(actor_telegram_id=body.actor_telegram_id, action="license_revoke", target_user_id=grant.user_id, grant_id=grant.id))
    db.commit()
    db.refresh(grant)
    return _public(grant)


@router.post("/v1/admin/licenses/{grant_id}/extend")
def extend(grant_id: int, body: Extend, db: Session = Depends(get_db)):
    _admin(body.actor_telegram_id)
    request_id = str(body.request_id)
    prior = db.get(LicenseOperation, request_id)
    if prior:
        if (prior.grant_id, prior.days, prior.actor_telegram_id) != (grant_id, body.days, body.actor_telegram_id):
            raise HTTPException(409, "Request ID used with different parameters")
        return {"id": grant_id, "expires_at": _utc(prior.result_expires_at), "replayed": True}
    grant = db.get(LicenseGrant, grant_id)
    if grant is None:
        raise HTTPException(404, "License not found")
    if grant.revoked_at is not None or grant.activated_at is None or grant.expires_at is None:
        raise HTTPException(409, "License is revoked or not activated")
    old = grant.expires_at
    new = max(_utc(old), _now()) + timedelta(days=body.days)
    # Optimistic compare-and-swap: a concurrent change causes an explicit conflict.
    changed = db.execute(update(LicenseGrant).where(
        LicenseGrant.id == grant_id, LicenseGrant.revoked_at.is_(None),
        LicenseGrant.expires_at == old
    ).values(expires_at=new))
    if not changed.rowcount:
        db.rollback()
        raise HTTPException(409, "License changed concurrently; retry")
    db.add(LicenseOperation(request_id=request_id, grant_id=grant_id, actor_telegram_id=body.actor_telegram_id, days=body.days, result_expires_at=new))
    db.add(AdminAudit(actor_telegram_id=body.actor_telegram_id, action="license_extend", target_user_id=grant.user_id, grant_id=grant_id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.get(LicenseOperation, request_id)
        if prior and (prior.grant_id, prior.days, prior.actor_telegram_id) == (grant_id, body.days, body.actor_telegram_id):
            return {"id": grant_id, "expires_at": _utc(prior.result_expires_at), "replayed": True}
        raise HTTPException(409, "Request ID conflict")
    return {"id": grant_id, "expires_at": new, "replayed": False}


@router.get("/v1/admin/errors")
def list_errors(actor_telegram_id: int, db: Session = Depends(get_db)):
    _admin(actor_telegram_id)
    errors=db.query(SystemError).order_by(SystemError.id.desc()).limit(50).all()
    return {"errors": [{"id":e.id,"component":e.component,"code":e.code,"job_id":e.job_id,"created_at":e.created_at} for e in errors]}


class PlanIssue(BaseModel):
    request_id: UUID
    actor_telegram_id: int = Field(gt=0)
    target_telegram_id: int = Field(gt=0)
    plan_id: UUID

@router.post('/v1/admin/licenses/from-plan', status_code=201)
def issue_from_plan(body: PlanIssue, db: Session = Depends(get_db)):
    _admin(body.actor_telegram_id)
    user=_user(db,body.target_telegram_id)
    plan=db.get(SubscriptionPlan,str(body.plan_id))
    if not plan or not plan.enabled: raise HTTPException(404,'Active plan not found')
    if db.query(LicenseGrant).filter_by(issue_request_id=str(body.request_id)).first():
        raise HTTPException(409,'Issue request already processed; key cannot be recovered')
    key='NORI-'+secrets.token_urlsafe(32)
    grant=LicenseGrant(user_id=user.id,key_hash=_hash(key),issue_request_id=str(body.request_id),duration_days=plan.duration_days)
    db.add(grant)
    try:
        db.flush()
        db.add(LicenseEntitlement(grant_id=grant.id,plan_id=plan.id,platform=plan.platform,device_limit=plan.device_limit))
        db.add(AdminAudit(actor_telegram_id=body.actor_telegram_id,action='license_plan_issue',target_user_id=user.id,grant_id=grant.id))
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'Issue request already processed')
    return {'id':grant.id,'key':key,'target_telegram_id':user.telegram_id,'duration_days':grant.duration_days,
            'plan_id':plan.id,'platform':plan.platform,'device_limit':plan.device_limit}
