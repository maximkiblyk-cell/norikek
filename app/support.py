"""Support conversations for the trusted bot service in a local test environment."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User, SupportTicket, SupportMessage, AdminAudit, NotificationJob, NotificationSetting
from app.licenses import _admin, _user

router = APIRouter()

class MessageInput(BaseModel):
    request_id: UUID
    text: str = Field(min_length=1, max_length=2000)

class AdminMessageInput(MessageInput):
    actor_telegram_id: int = Field(gt=0)

class AdminInput(BaseModel):
    actor_telegram_id: int = Field(gt=0)

def owner_ticket(db, telegram_id, ticket_id):
    user = _user(db, telegram_id)
    ticket = db.query(SupportTicket).filter_by(id=ticket_id, user_id=user.id).first()
    if ticket is None:
        raise HTTPException(404, "Ticket not found")
    return ticket

def detail(db, ticket):
    rows = db.query(SupportMessage).filter_by(ticket_id=ticket.id).order_by(SupportMessage.id.desc()).limit(200).all()
    rows.reverse()
    return {"id": ticket.id, "category": ticket.category, "status": ticket.status,
            "created_at": ticket.created_at, "initial_message": ticket.message,
            "messages": [{"id": r.id, "author_type": r.author_type, "text": r.text, "created_at": r.created_at} for r in rows]}

def add_message(db, ticket, actor_id, author_type, body):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Message cannot be blank")
    request_id = str(body.request_id)
    previous = db.query(SupportMessage).filter_by(request_id=request_id).first()
    if previous:
        if (previous.ticket_id, previous.author_telegram_id, previous.author_type, previous.text) != (ticket.id, actor_id, author_type, text):
            raise HTTPException(409, "Request ID conflict")
        return {"id": previous.id, "status": "saved", "replayed": True}
    if ticket.status != "open":
        raise HTTPException(409, "Ticket is closed")
    item = SupportMessage(ticket_id=ticket.id, author_type=author_type, author_telegram_id=actor_id, text=text, request_id=request_id)
    db.add(item)
    try:
        db.flush()
        if author_type == "admin":
            db.add(AdminAudit(actor_telegram_id=actor_id, action="support_reply", target_user_id=ticket.user_id))
            opt_in = db.query(NotificationSetting).filter_by(user_id=ticket.user_id, kind="system", enabled=True).first()
            if opt_in:
                db.add(NotificationJob(user_id=ticket.user_id, support_message_id=item.id, ticket_id=ticket.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.query(SupportMessage).filter_by(request_id=request_id).first()
        if prior and (prior.ticket_id, prior.author_telegram_id, prior.author_type, prior.text) == (ticket.id, actor_id, author_type, text):
            return {"id": prior.id, "status": "saved", "replayed": True}
        raise HTTPException(409, "Request ID conflict")
    db.refresh(item)
    return {"id": item.id, "status": "saved", "replayed": False}

@router.get("/v1/users/{telegram_id}/tickets/{ticket_id}")
def user_view(telegram_id: int, ticket_id: int, db: Session = Depends(get_db)):
    return detail(db, owner_ticket(db, telegram_id, ticket_id))

@router.post("/v1/users/{telegram_id}/tickets/{ticket_id}/messages")
def user_reply(telegram_id: int, ticket_id: int, body: MessageInput, db: Session = Depends(get_db)):
    return add_message(db, owner_ticket(db, telegram_id, ticket_id), telegram_id, "user", body)

@router.post("/v1/users/{telegram_id}/tickets/{ticket_id}/close")
def user_close(telegram_id: int, ticket_id: int, db: Session = Depends(get_db)):
    ticket = owner_ticket(db, telegram_id, ticket_id)
    ticket.status = "closed"
    db.commit()
    return {"id": ticket.id, "status": ticket.status}

@router.get("/v1/admin/tickets")
def admin_list(actor_telegram_id: int = Query(gt=0), db: Session = Depends(get_db)):
    _admin(actor_telegram_id)
    rows = db.query(SupportTicket).filter_by(status="open").order_by(SupportTicket.id.desc()).limit(50).all()
    return {"tickets": [{"id": r.id, "category": r.category, "status": r.status} for r in rows]}

@router.get("/v1/admin/tickets/{ticket_id}")
def admin_view(ticket_id: int, actor_telegram_id: int = Query(gt=0), db: Session = Depends(get_db)):
    _admin(actor_telegram_id)
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Ticket not found")
    out = detail(db, ticket)
    user = db.get(User, ticket.user_id)
    out["telegram_id"] = user.telegram_id
    return out

@router.post("/v1/admin/tickets/{ticket_id}/messages")
def admin_reply(ticket_id: int, body: AdminMessageInput, db: Session = Depends(get_db)):
    _admin(body.actor_telegram_id)
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Ticket not found")
    return add_message(db, ticket, body.actor_telegram_id, "admin", body)

@router.post("/v1/admin/tickets/{ticket_id}/close")
def admin_close(ticket_id: int, body: AdminInput, db: Session = Depends(get_db)):
    _admin(body.actor_telegram_id)
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, "Ticket not found")
    changed = db.execute(update(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.status == "open").values(status="closed"))
    if changed.rowcount:
        db.add(AdminAudit(actor_telegram_id=body.actor_telegram_id, action="support_close", target_user_id=ticket.user_id))
    db.commit()
    return {"id": ticket_id, "status": "closed"}


@router.get("/v1/users/{telegram_id}/notifications")
def user_notifications(telegram_id: int, db: Session = Depends(get_db)):
    user = _user(db, telegram_id)
    rows = db.query(NotificationJob).filter_by(user_id=user.id).order_by(NotificationJob.id.desc()).limit(50).all()
    return {"notifications": [{"id": row.id, "kind": "support_reply", "ticket_id": row.ticket_id,
                               "status": row.status, "attempts": row.attempts, "sent_at": row.sent_at} for row in rows]}
