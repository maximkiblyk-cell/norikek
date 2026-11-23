"""Shared fail-closed v2 entitlement and database-backed rate limits."""
from datetime import datetime,timezone
import hashlib,time
from fastapi import HTTPException,Header,Depends,Request
from sqlalchemy import text
from app.auth import digest,utc
from app.core.config import settings
from app.db import get_db
from app.models import Device,LicenseGrant,LicenseEntitlement,AccountAccess,User
from app.v2.models import RateBucket

def now(): return datetime.now(timezone.utc)
def begin_write(db):
    # SQLite has no row-level FOR UPDATE; acquire its single write reservation.
    if db.bind.dialect.name=='sqlite':
        raw=db.connection().connection.driver_connection
        if not raw.in_transaction: db.execute(text('BEGIN IMMEDIATE'))

def limit(db, category, scope, maximum, seconds=600):
    dialect=db.bind.dialect.name
    if dialect=='sqlite': from sqlalchemy.dialects.sqlite import insert
    elif dialect=='postgresql': from sqlalchemy.dialects.postgresql import insert
    else: raise HTTPException(503,'Unsupported rate-limit storage')
    bucket=int(time.time())//seconds
    obj={'category':category,'scope_hash':hashlib.sha256(scope.encode()).hexdigest(),'window':bucket,'count':1}
    stmt=insert(RateBucket).values(**obj)
    stmt=stmt.on_conflict_do_update(index_elements=['category','scope_hash','window'],set_={'count':RateBucket.count+1}).returning(RateBucket.count)
    count=db.execute(stmt).scalar_one();db.commit()
    if count>maximum: raise HTTPException(429,'Rate limit exceeded',headers={'Retry-After':str(seconds-int(time.time())%seconds)})

def ip_limit(db,request:Request,category,maximum=30):
    limit(db,category,'ip:'+(request.client.host if request.client else 'unknown'),maximum)

def evaluate(db,grant,device=None,user_id=None):
    moment=now()
    if not grant or (user_id is not None and grant.user_id!=user_id): return None,'LICENSE_UNAVAILABLE'
    if not db.get(User,grant.user_id): return None,'ACCOUNT_UNAVAILABLE'
    account=db.get(AccountAccess,grant.user_id)
    if account and account.disabled: return None,'ACCOUNT_BLOCKED'
    if grant.revoked_at: return None,'LICENSE_REVOKED'
    if not grant.activated_at or utc(grant.activated_at)>moment: return None,'LICENSE_NOT_ACTIVE'
    if not grant.expires_at or utc(grant.expires_at)<=moment: return None,'LICENSE_EXPIRED'
    snapshot=db.get(LicenseEntitlement,grant.id)
    if not snapshot or snapshot.device_limit<1 or snapshot.platform not in ('both','hassle','radmir'): return None,'ENTITLEMENT_UNAVAILABLE'
    if device:
        if device.user_id!=grant.user_id or device.license_id!=grant.id or device.status!='active' or not device.credential_hash: return None,'DEVICE_UNAVAILABLE'
        if snapshot.platform not in ('both',device.platform): return None,'PLATFORM_DENIED'
        count=db.query(Device).filter(Device.license_id==grant.id,Device.status=='active').count()
        if count>snapshot.device_limit: return None,'DEVICE_LIMIT'
    return snapshot,None

def device_auth(request:Request, authorization:str|None=Header(default=None), db=Depends(get_db)):
    ip_limit(db,request,'device_auth',1000)
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Invalid device credentials')
    raw=authorization[7:]
    if len(raw)<32 or len(raw)>100: raise HTTPException(401,'Invalid device credentials')
    device=db.query(Device).filter_by(credential_hash=digest(raw),status='active').first()
    if not device: raise HTTPException(401,'Invalid device credentials')
    snap,reason=evaluate(db,db.get(LicenseGrant,device.license_id),device)
    if reason: raise HTTPException(403,reason)
    return device

def locked_device(db,device):
    begin_write(db)
    grant=db.query(LicenseGrant).filter_by(id=device.license_id).with_for_update().first()
    d=db.query(Device).filter_by(id=device.id).with_for_update().populate_existing().first()
    snap,reason=evaluate(db,grant,d)
    if reason: raise HTTPException(403,reason)
    return d,grant,snap

def approved(setting): return {x.strip() for x in setting.split(',') if x.strip()}
