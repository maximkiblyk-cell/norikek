from datetime import timedelta
from uuid import uuid4,UUID
import hmac,secrets
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy.orm import Session
from app.auth import require_identity,digest,utc
from app.db import get_db
from app.models import Device,LicenseGrant,AdminAudit
from app.v2.models import PairingV2
from app.v2.security import now,evaluate,begin_write,ip_limit,limit,device_auth

router=APIRouter(prefix='/v2')
class Strict(BaseModel): model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
class Start(Strict):
    platform:Literal['hassle_rp_2','radmir_crmp']
    name:str=Field(min_length=1,max_length=80)
class Preview(Strict): pairing_code:str=Field(pattern=r'^[A-Z2-7]{16}$')
class Confirm(Preview):
    pairing_id:UUID
    license_id:int=Field(gt=0)
class Claim(Strict):
    pairing_id:UUID
    claim_secret:str=Field(min_length=32,max_length=100)

platforms={'hassle_rp_2':'hassle','radmir_crmp':'radmir'}
reverse={v:k for k,v in platforms.items()}
def get_pair(db,id): return db.query(PairingV2).filter_by(id=str(id)).with_for_update().populate_existing().first()
def valid(pair):
    if not pair: raise HTTPException(404,'Pairing unavailable')
    if pair.cancelled_at: raise HTTPException(409,'Pairing unavailable')
    from app.auth import utc
    if utc(pair.expires_at)<=now(): raise HTTPException(410,'Pairing expired')

def public(p): return {'pairing_id':p.id,'device_id_suffix':p.proposed_device_id[-4:],'name':p.name,'platform':reverse[p.platform],'expires_at':utc(p.expires_at)}

@router.post('/device/pairings',status_code=201)
def start(body:Start,request:Request,db:Session=Depends(get_db)):
    ip_limit(db,request,'pair_start',10)
    code=''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567') for _ in range(16));claim=secrets.token_urlsafe(32)
    pair=PairingV2(id=str(uuid4()),proposed_device_id=str(uuid4()),code_hash=digest(code),claim_hash=digest(claim),platform=platforms[body.platform],name=body.name,expires_at=now()+timedelta(seconds=300))
    db.add(pair);db.commit()
    return {'pairing_id':pair.id,'device_id':pair.proposed_device_id,'pairing_code':code,'claim_secret':claim,'expires_at':utc(pair.expires_at)}

@router.post('/pairings/preview')
def preview(body:Preview,request:Request,principal=Depends(require_identity),db:Session=Depends(get_db)):
    ip_limit(db,request,'pair_preview_ip',60);limit(db,'pair_preview_user',str(principal.user_id),15)
    p=db.query(PairingV2).filter_by(code_hash=digest(body.pairing_code)).first();valid(p)
    if p.confirmed_at: raise HTTPException(409,'Pairing unavailable')
    return public(p)

@router.post('/pairings/confirm')
def confirm(body:Confirm,request:Request,principal=Depends(require_identity),db:Session=Depends(get_db)):
    ip_limit(db,request,'pair_confirm_ip',60);limit(db,'pair_confirm_user',str(principal.user_id),15)
    begin_write(db);p=get_pair(db,body.pairing_id);valid(p)
    if not hmac.compare_digest(p.code_hash,digest(body.pairing_code)): raise HTTPException(404,'Pairing unavailable')
    if p.confirmed_at:raise HTTPException(409,'Pairing already confirmed')
    grant=db.query(LicenseGrant).filter_by(id=body.license_id,user_id=principal.user_id).with_for_update().first()
    snapshot,reason=evaluate(db,grant,user_id=principal.user_id)
    if reason: raise HTTPException(403,reason)
    if snapshot.platform not in ('both',p.platform):raise HTTPException(403,'PLATFORM_DENIED')
    # Expire stale reservations, then serialize count under grant lock or SQLite write lock.
    db.query(Device).filter(Device.license_id==grant.id,Device.status=='pending',Device.pending_expires_at<=now()).update({'status':'expired'},synchronize_session=False)
    count=db.query(Device).filter(Device.license_id==grant.id,Device.status.in_(['pending','active'])).count()
    if count>=snapshot.device_limit:raise HTTPException(409,'DEVICE_LIMIT')
    device=Device(id=p.proposed_device_id,user_id=principal.user_id,license_id=grant.id,platform=p.platform,name=p.name,status='pending',pending_expires_at=p.expires_at)
    db.add(device);db.flush();p.device_id=device.id;p.user_id=principal.user_id;p.grant_id=grant.id;p.confirmed_at=now();db.add(AdminAudit(actor_telegram_id=principal.telegram_id,action='pair_confirm',target_user_id=principal.user_id,grant_id=grant.id));db.commit()
    return {'pairing_id':p.id,'status':'confirmed','expires_at':utc(p.expires_at)}

@router.post('/device/pairings/claim')
def claim(body:Claim,request:Request,db:Session=Depends(get_db)):
    ip_limit(db,request,'pair_claim_ip',60);limit(db,'pair_claim_id',str(body.pairing_id),10)
    begin_write(db);p=get_pair(db,body.pairing_id)
    if not p or not hmac.compare_digest(p.claim_hash,digest(body.claim_secret)):raise HTTPException(401,'Invalid claim')
    valid(p)
    if p.claimed_at:raise HTTPException(409,'Pairing already claimed')
    if not p.confirmed_at or not p.device_id:raise HTTPException(409,'Pairing not confirmed')
    grant=db.query(LicenseGrant).filter_by(id=p.grant_id).with_for_update().first();d=db.query(Device).filter_by(id=p.device_id).with_for_update().first()
    snap,reason=evaluate(db,grant,user_id=p.user_id)
    if reason:raise HTTPException(403,reason)
    if not d or d.status!='pending' or d.user_id!=p.user_id or d.license_id!=p.grant_id or snap.platform not in ('both',d.platform):raise HTTPException(403,'Device unavailable')
    count=db.query(Device).filter(Device.license_id==p.grant_id,Device.status.in_(['pending','active'])).count()
    if count>snap.device_limit:raise HTTPException(409,'DEVICE_LIMIT')
    token=secrets.token_urlsafe(32);d.credential_hash=digest(token);d.status='active';d.pending_expires_at=None;p.claimed_at=now();db.commit()
    return {'device_id':d.id,'device_credential':token,'credential_type':'Bearer'}

@router.post('/pairings/{pairing_id}/cancel')
def cancel(pairing_id:UUID,request:Request,principal=Depends(require_identity),db:Session=Depends(get_db)):
    ip_limit(db,request,'pair_cancel',60);begin_write(db);p=get_pair(db,pairing_id)
    if not p or p.user_id!=principal.user_id:raise HTTPException(404,'Pairing unavailable')
    if not p.cancelled_at:
        p.cancelled_at=now();d=db.query(Device).filter_by(id=p.device_id,user_id=principal.user_id).with_for_update().first()
        if d:d.status='revoked';d.credential_hash=None;d.revoked_at=now()
        db.add(AdminAudit(actor_telegram_id=principal.telegram_id,action='pair_cancel',target_user_id=principal.user_id,grant_id=p.grant_id));db.commit()
    return {'pairing_id':p.id,'status':'cancelled'}

@router.post('/devices/{device_id}/revoke')
def revoke(device_id:UUID,request:Request,principal=Depends(require_identity),db:Session=Depends(get_db)):
    ip_limit(db,request,'device_revoke',60);begin_write(db);d=db.query(Device).filter_by(id=str(device_id),user_id=principal.user_id).with_for_update().first()
    if not d:raise HTTPException(404,'Device unavailable')
    if d.status!='revoked':
        d.status='revoked';d.revoked_at=now();d.credential_hash=None;db.add(AdminAudit(actor_telegram_id=principal.telegram_id,action='device_revoke',target_user_id=principal.user_id,grant_id=d.license_id));db.commit()
    return {'device_id':d.id,'status':'revoked'}

@router.get('/device/access')
def access(device:Device=Depends(device_auth),db:Session=Depends(get_db)):
    from app.v2.security import approved
    from app.core.config import settings
    grant=db.get(LicenseGrant,device.license_id);snapshot,reason=evaluate(db,grant,device)
    if reason:raise HTTPException(403,reason)
    checked=now();device.last_seen_at=checked;db.commit()
    return {'device_id':device.id,'license_id':grant.id,'platform':reverse[device.platform],'status':'active','expires_at':utc(grant.expires_at),'server_time':checked,'last_checked_at':checked,'device_limit':snapshot.device_limit,'features':sorted(['event:'+x for x in approved(settings.v2_approved_event_types)]+['command:'+x for x in approved(settings.v2_approved_command_types)])}

@router.get('/licenses')
def user_licenses(principal=Depends(require_identity),db:Session=Depends(get_db)):
    grants=db.query(LicenseGrant).filter_by(user_id=principal.user_id).order_by(LicenseGrant.id.desc()).limit(100).all()
    output=[]
    for grant in grants:
        snapshot,reason=evaluate(db,grant,user_id=principal.user_id)
        output.append({'license_id':grant.id,'allowed':reason is None,'reason':reason,'expires_at':utc(grant.expires_at) if grant.expires_at else None,'platform':snapshot.platform if snapshot else None,'device_limit':snapshot.device_limit if snapshot else None,'checked_at':now()})
    return {'licenses':output}
