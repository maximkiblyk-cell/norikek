"""Independent event and command persistence. No game adapters or game SDK calls."""
import json,secrets,hashlib
from datetime import timedelta
from uuid import UUID,uuid4
from typing import Any
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.auth import require_identity,digest,utc
from app.models import Device
from app.v2.models import GameEvent,GameEventJob,RemoteCommand
from app.v2.security import now,begin_write,locked_device,device_auth,approved,ip_limit
from app.core.config import settings
router=APIRouter(prefix='/v2')
class Strict(BaseModel): model_config=ConfigDict(extra='forbid')
def canonical(value):
    try: raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
    except (TypeError,ValueError):raise HTTPException(422,'Invalid payload')
    if len(raw.encode())>4096:raise HTTPException(422,'Payload too large')
    return raw
class Event(Strict):
    event_id:UUID
    event_type:str=Field(min_length=1,max_length=32,pattern=r'^[a-z][a-z0-9_]*$')
    payload:dict[str,Any]
class Command(Strict):
    device_id:UUID
    idempotency_key:str=Field(min_length=16,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    command_type:str=Field(min_length=1,max_length=32,pattern=r'^[a-z][a-z0-9_]*$')
    payload:dict[str,Any]
    ttl_seconds:int=Field(ge=10,le=3600,default=300)
class Ack(Strict): lease_token:str=Field(min_length=32,max_length=100)
class Result(Ack): result:str=Field(pattern=r'^(FAILED|EXECUTED)$')

def require_type(typ,setting):
    if typ not in approved(setting):raise HTTPException(503,'Type not approved or available')
def view(c):
    return {'command_id':c.id,'status':c.status,'expires_at':utc(c.expires_at),'attempts':c.attempts,'error_code':c.error_code}
def expire(c):
    t=now()
    if c.status=='PENDING' and utc(c.expires_at)<=t:c.status='EXPIRED';c.lease_hash=None;c.lease_until=None
    if c.status=='ACKNOWLEDGED' and c.acknowledged_at and utc(c.acknowledged_at)+timedelta(seconds=120)<=t:c.status='FAILED';c.error_code='EXECUTION_UNKNOWN'

def owned(db,id,user_id):
    c=db.query(RemoteCommand).filter_by(id=str(id),user_id=user_id).with_for_update().first()
    if not c:raise HTTPException(404,'Command unavailable')
    return c

def device_command(db,id,device):
    c=db.query(RemoteCommand).filter_by(id=str(id),device_id=device.id).with_for_update().first()
    if not c:raise HTTPException(404,'Command unavailable')
    return c

@router.post('/events',status_code=202)
def event(body:Event,request:Request,device=Depends(device_auth),db=Depends(get_db)):
    ip_limit(db,request,'event',300);require_type(body.event_type,settings.v2_approved_event_types)
    raw=canonical(body.payload);h=hashlib.sha256((body.event_type+'\n'+raw).encode()).hexdigest()
    begin_write(db);device,_,_=locked_device(db,device)
    old=db.query(GameEvent).filter_by(device_id=device.id,event_id=str(body.event_id)).first()
    if old:
        if old.payload_hash!=h:raise HTTPException(409,'Event conflict')
        return {'accepted':True,'replayed':True,'event_id':old.event_id}
    e=GameEvent(id=str(uuid4()),device_id=device.id,event_id=str(body.event_id),user_id=device.user_id,event_type=body.event_type,payload=raw,payload_hash=h)
    db.add(e)
    try:
        db.flush();db.add(GameEventJob(id=str(uuid4()),event_id=e.id,user_id=device.user_id,status='pending',attempts=0,next_attempt_at=now()));db.commit()
    except IntegrityError:
        db.rollback();old=db.query(GameEvent).filter_by(device_id=device.id,event_id=str(body.event_id)).first()
        if old and old.payload_hash==h:return {'accepted':True,'replayed':True,'event_id':old.event_id}
        raise HTTPException(409,'Event conflict')
    return {'accepted':True,'replayed':False,'event_id':e.event_id}

@router.post('/commands',status_code=201)
def create(body:Command,request:Request,principal=Depends(require_identity),db=Depends(get_db)):
    ip_limit(db,request,'command_create',120);require_type(body.command_type,settings.v2_approved_command_types)
    raw=canonical(body.payload);h=hashlib.sha256((str(body.device_id)+'\n'+body.command_type+'\n'+str(body.ttl_seconds)+'\n'+raw).encode()).hexdigest()
    begin_write(db)
    old=db.query(RemoteCommand).filter_by(user_id=principal.user_id,idempotency_key=body.idempotency_key).first()
    if old:
        if old.request_hash!=h:raise HTTPException(409,'Idempotency conflict')
        expire(old);db.commit();return {**view(old),'replayed':True}
    d=db.query(Device).filter_by(id=str(body.device_id),user_id=principal.user_id).first()
    if not d:raise HTTPException(404,'Device unavailable')
    d,_,_=locked_device(db,d)
    c=RemoteCommand(id=str(uuid4()),user_id=principal.user_id,device_id=d.id,idempotency_key=body.idempotency_key,request_hash=h,command_type=body.command_type,payload=raw,status='PENDING',created_at=now(),expires_at=now()+timedelta(seconds=body.ttl_seconds),attempts=0)
    db.add(c)
    try:db.commit()
    except IntegrityError:
        db.rollback();old=db.query(RemoteCommand).filter_by(user_id=principal.user_id,idempotency_key=body.idempotency_key).first()
        if old and old.request_hash==h:return {**view(old),'replayed':True}
        raise HTTPException(409,'Idempotency conflict')
    return {**view(c),'replayed':False}

@router.get('/commands/{command_id}')
def inspect(command_id:UUID,principal=Depends(require_identity),db=Depends(get_db)):
    begin_write(db);c=owned(db,command_id,principal.user_id);expire(c);db.commit();return view(c)

@router.post('/commands/{command_id}/cancel')
def cancel(command_id:UUID,request:Request,principal=Depends(require_identity),db=Depends(get_db)):
    ip_limit(db,request,'command_cancel',120);begin_write(db);c=owned(db,command_id,principal.user_id);expire(c)
    if c.status=='CANCELLED':return view(c)
    if c.status!='PENDING':db.commit();raise HTTPException(409,'Too late to cancel')
    c.status='CANCELLED';c.lease_hash=None;c.lease_until=None;db.commit();return view(c)

@router.post('/device/commands/claim')
def claim(request:Request,device=Depends(device_auth),db=Depends(get_db)):
    ip_limit(db,request,'command_claim',300);begin_write(db);device,_,_=locked_device(db,device);t=now()
    rows=db.query(RemoteCommand).filter_by(device_id=device.id).filter(RemoteCommand.status.in_(['PENDING','ACKNOWLEDGED'])).order_by(RemoteCommand.created_at).with_for_update().limit(100).all()
    chosen=None
    for c in rows:
        expire(c)
        if c.status!='PENDING':continue
        if c.command_type not in approved(settings.v2_approved_command_types):
            c.status='CANCELLED';c.error_code='TYPE_DISABLED';c.lease_hash=None;c.lease_until=None;continue
        if c.lease_until and utc(c.lease_until)>t:continue
        if c.lease_until:
            c.lease_until=None;c.lease_hash=None
            if c.attempts>=5:c.status='FAILED';c.error_code='ACK_TIMEOUT';continue
            c.next_attempt_at=t+timedelta(seconds=min(16,2**(c.attempts-1)));continue
        if c.next_attempt_at and utc(c.next_attempt_at)>t:continue
        chosen=c;break
    if not chosen:db.commit();return {'command':None}
    token=secrets.token_urlsafe(32);chosen.lease_hash=digest(token);chosen.lease_until=min(t+timedelta(seconds=30),utc(chosen.expires_at));chosen.attempts+=1;chosen.next_attempt_at=None;db.commit()
    return {'command':{**view(chosen),'type':chosen.command_type,'payload':json.loads(chosen.payload),'lease_token':token,'lease_until':utc(chosen.lease_until)}}

@router.post('/device/commands/{command_id}/ack')
def ack(command_id:UUID,body:Ack,request:Request,device=Depends(device_auth),db=Depends(get_db)):
    ip_limit(db,request,'command_ack',300);begin_write(db);device,_,_=locked_device(db,device);c=device_command(db,command_id,device);expire(c)
    require_type(c.command_type,settings.v2_approved_command_types)
    if not c.lease_hash or not hmac_compare(c.lease_hash,digest(body.lease_token)):db.commit();raise HTTPException(409,'Lease unavailable')
    if c.status=='ACKNOWLEDGED':return view(c)
    if c.status!='PENDING' or not c.lease_until or utc(c.lease_until)<=now():db.commit();raise HTTPException(409,'Lease expired')
    c.status='ACKNOWLEDGED';c.acknowledged_at=now();c.lease_until=None;db.commit();return view(c)

def hmac_compare(a,b):
    import hmac
    return hmac.compare_digest(a,b)

@router.post('/device/commands/{command_id}/authorize')
def authorize(command_id:UUID,body:Ack,device=Depends(device_auth),db=Depends(get_db)):
    begin_write(db);device,_,_=locked_device(db,device);c=device_command(db,command_id,device);expire(c)
    require_type(c.command_type,settings.v2_approved_command_types)
    if c.status!='ACKNOWLEDGED' or not c.lease_hash or not hmac_compare(c.lease_hash,digest(body.lease_token)) or utc(c.expires_at)<=now():db.commit();raise HTTPException(403,'Command unavailable')
    # A live response is not an offline capability; there is an unavoidable revocation race after response.
    return {'authorized':True,'checked_at':now(),'command_id':c.id,'expires_at':utc(c.expires_at)}

@router.post('/device/commands/{command_id}/result')
def result(command_id:UUID,body:Result,device=Depends(device_auth),db=Depends(get_db)):
    begin_write(db);device,_,_=locked_device(db,device);c=device_command(db,command_id,device);expire(c)
    if not c.lease_hash or not hmac_compare(c.lease_hash,digest(body.lease_token)):raise HTTPException(409,'Lease unavailable')
    if c.status=='FAILED' and body.result=='FAILED':return view(c)
    if c.status!='ACKNOWLEDGED':db.commit();raise HTTPException(409,'Command unavailable')
    if body.result=='EXECUTED':raise HTTPException(503,'Game execution verifier not available')
    c.status='FAILED';c.error_code='DEVICE_REPORTED_FAILURE';c.result_at=now();db.commit();return view(c)
