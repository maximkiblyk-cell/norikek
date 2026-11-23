"""Plan configuration and payment-provider boundary. No provider is configured."""
from typing import Literal, Protocol
from uuid import uuid4, UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db import get_db
from app.models import SubscriptionPlan, AdminAudit
from app.licenses import _admin

router = APIRouter()

class PaymentProvider(Protocol):
    async def create_payment(self, *, external_id: str, amount_minor: int, currency: str) -> dict: ...
    async def verify_webhook(self, *, headers: dict, body: bytes) -> dict: ...

class PlanCreate(BaseModel):
    request_id: UUID
    actor_telegram_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    price_minor: int = Field(ge=0, le=1000000000)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    duration_days: int = Field(ge=1, le=3650)
    device_limit: int = Field(ge=1, le=100)
    platform: Literal['hassle','radmir','both']

class PaymentRequest(BaseModel):
    plan_id: str = Field(min_length=36,max_length=36)
    telegram_id: int = Field(gt=0)

def public(row):
    return {'id':row.id,'name':row.name,'price_minor':row.price_minor,'currency':row.currency,
            'duration_days':row.duration_days,'device_limit':row.device_limit,'platform':row.platform,'enabled':row.enabled}

@router.post('/v1/admin/plans',status_code=201)
def create_plan(body: PlanCreate,db:Session=Depends(get_db)):
    _admin(body.actor_telegram_id)
    if not body.name.strip(): raise HTTPException(422,'Plan name required')
    request_id = str(body.request_id)
    def prior():
        row=db.query(SubscriptionPlan).filter_by(request_id=request_id).first()
        if row and (row.created_by,row.name,row.price_minor,row.currency,row.duration_days,row.device_limit,row.platform) != (body.actor_telegram_id,body.name.strip(),body.price_minor,body.currency,body.duration_days,body.device_limit,body.platform):
            raise HTTPException(409, 'Request ID conflict')
        return row
    row=prior()
    if row: return public(row)
    row=SubscriptionPlan(id=str(uuid4()),request_id=request_id,created_by=body.actor_telegram_id,name=body.name.strip(),price_minor=body.price_minor,currency=body.currency,
                         duration_days=body.duration_days,device_limit=body.device_limit,platform=body.platform,enabled=True)
    db.add(row);db.add(AdminAudit(actor_telegram_id=body.actor_telegram_id,action='plan_create'))
    try: db.commit()
    except IntegrityError:
        db.rollback(); row=prior()
        if row is None: raise HTTPException(409,'Request ID conflict')
    return public(row)

@router.get('/v1/plans')
def list_plans(db:Session=Depends(get_db)):
    return {'plans':[public(x) for x in db.query(SubscriptionPlan).filter_by(enabled=True).order_by(SubscriptionPlan.created_at).all()]}

@router.post('/v1/payments')
def create_payment(body: PaymentRequest):
    # A real provider must be selected and integrated with verified webhook signatures,
    # idempotency, payment reconciliation and server-side access issuance.
    raise HTTPException(503,'Payment provider not configured; no payment created')
