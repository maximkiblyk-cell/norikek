"""Administrative operations protected by per-request identity and RBAC."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, AccountAccess, AuthSession, LicenseGrant, Device, SubscriptionPlan, AdminAudit
from app.auth import owner_ids, role_for
from app.licenses import _public
from app.devices import public_device, timestamp
from app.payments import public as plan_public

router=APIRouter(prefix='/v1/admin')

def user_by_id(db,telegram_id):
    user=db.query(User).filter_by(telegram_id=telegram_id).first()
    if not user: raise HTTPException(404,'User not found')
    return user

def view_user(db,u):
    access=db.get(AccountAccess,u.id)
    return {'telegram_id':u.telegram_id,'username':u.username,'created_at':u.created_at,
            'role':role_for(u,access),'disabled':bool(access and access.disabled)}

def ensure_target(actor,user,db):
    role=role_for(user,db.get(AccountAccess,user.id))
    if user.telegram_id in owner_ids() or (actor.role!='owner' and role!='user'):
        raise HTTPException(403,'Cannot change this account')

class RoleInput(BaseModel):
    role: Literal['user','admin']
class DisabledInput(BaseModel):
    disabled: bool
class PlanEnabledInput(BaseModel):
    enabled: bool

@router.get('/users')
def list_users(db:Session=Depends(get_db)):
    return {'users':[view_user(db,u) for u in db.query(User).order_by(User.id.desc()).limit(100).all()]}

@router.get('/users/{telegram_id}')
def get_user(telegram_id:int,db:Session=Depends(get_db)):
    return view_user(db,user_by_id(db,telegram_id))

@router.post('/users/{telegram_id}/role')
def set_role(telegram_id:int,body:RoleInput,request:Request,db:Session=Depends(get_db)):
    actor=request.state.principal
    if actor.role!='owner': raise HTTPException(403,'Owner access required')
    user=user_by_id(db,telegram_id);ensure_target(actor,user,db)
    access=db.get(AccountAccess,user.id)
    if not access: access=AccountAccess(user_id=user.id,role='user',disabled=False);db.add(access)
    if access.role!=body.role:
        access.role=body.role;db.add(AdminAudit(actor_telegram_id=actor.telegram_id,action='role_'+body.role,target_user_id=user.id))
    db.commit()
    return view_user(db,user)

@router.post('/users/{telegram_id}/disabled')
def set_disabled(telegram_id:int,body:DisabledInput,request:Request,db:Session=Depends(get_db)):
    actor=request.state.principal;user=user_by_id(db,telegram_id);ensure_target(actor,user,db)
    access=db.get(AccountAccess,user.id)
    if not access: access=AccountAccess(user_id=user.id,role='user',disabled=False);db.add(access)
    if access.disabled != body.disabled:
        access.disabled=body.disabled
        if body.disabled:
            db.query(AuthSession).filter_by(user_id=user.id).delete(synchronize_session=False)
        db.add(AdminAudit(actor_telegram_id=actor.telegram_id,action='user_disable' if body.disabled else 'user_enable',target_user_id=user.id))
    db.commit();return view_user(db,user)

@router.get('/users/{telegram_id}/licenses')
def admin_user_licenses(telegram_id:int,db:Session=Depends(get_db)):
    u=user_by_id(db,telegram_id)
    return {'licenses':[_public(g) for g in db.query(LicenseGrant).filter_by(user_id=u.id).order_by(LicenseGrant.id.desc()).limit(100).all()]}

@router.get('/users/{telegram_id}/devices')
def admin_user_devices(telegram_id:int,db:Session=Depends(get_db)):
    u=user_by_id(db,telegram_id)
    return {'devices':[public_device(d) for d in db.query(Device).filter_by(user_id=u.id).order_by(Device.created_at.desc()).limit(100).all()]}

@router.post('/users/{telegram_id}/devices/{device_id}/revoke')
def admin_device_revoke(telegram_id:int,device_id:str,request:Request,db:Session=Depends(get_db)):
    user=user_by_id(db,telegram_id);ensure_target(request.state.principal,user,db)
    device=db.query(Device).filter_by(id=device_id,user_id=user.id).first()
    if not device: raise HTTPException(404,'Device not found')
    if device.status!='revoked':
        device.status='revoked';device.revoked_at=timestamp();device.credential_hash=None
        db.add(AdminAudit(actor_telegram_id=request.state.principal.telegram_id,action='device_revoke',target_user_id=user.id))
    db.commit()
    return public_device(device)

@router.get('/plans')
def admin_plans(db:Session=Depends(get_db)):
    return {'plans':[plan_public(p) for p in db.query(SubscriptionPlan).order_by(SubscriptionPlan.created_at.desc()).limit(100).all()]}

@router.post('/plans/{plan_id}/enabled')
def set_plan_enabled(plan_id:str,body:PlanEnabledInput,request:Request,db:Session=Depends(get_db)):
    plan=db.get(SubscriptionPlan,plan_id)
    if not plan: raise HTTPException(404,'Plan not found')
    if plan.enabled!=body.enabled:
        plan.enabled=body.enabled;db.add(AdminAudit(actor_telegram_id=request.state.principal.telegram_id,action='plan_enable' if body.enabled else 'plan_disable'))
    db.commit();return plan_public(plan)
