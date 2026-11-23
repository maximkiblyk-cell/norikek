"""v2 tables; license_grants and license_entitlements remain the canonical sources."""
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, DateTime, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base
from app.models import utcnow

class PairingV2(Base):
    __tablename__='v2_pairings'
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    proposed_device_id:Mapped[str]=mapped_column(String(36),unique=True,nullable=False)
    code_hash:Mapped[str]=mapped_column(String(64),unique=True,nullable=False)
    claim_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    platform:Mapped[str]=mapped_column(String(16),nullable=False)
    name:Mapped[str]=mapped_column(String(80),nullable=False)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    confirmed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    claimed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    cancelled_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    user_id:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    grant_id:Mapped[int|None]=mapped_column(ForeignKey('license_grants.id'),nullable=True)
    device_id:Mapped[str|None]=mapped_column(ForeignKey('devices.id'),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)

class RateBucket(Base):
    __tablename__='v2_rate_buckets'
    category:Mapped[str]=mapped_column(String(32),primary_key=True)
    scope_hash:Mapped[str]=mapped_column(String(64),primary_key=True)
    window:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    count:Mapped[int]=mapped_column(Integer,nullable=False)

class GameEvent(Base):
    __tablename__='game_events'
    __table_args__=(UniqueConstraint('device_id','event_id',name='uq_game_event_device_event'),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    device_id:Mapped[str]=mapped_column(ForeignKey('devices.id'),nullable=False,index=True)
    event_id:Mapped[str]=mapped_column(String(36),nullable=False)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),nullable=False)
    event_type:Mapped[str]=mapped_column(String(32),nullable=False)
    payload:Mapped[str]=mapped_column(Text,nullable=False)
    payload_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    received_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)

class GameEventJob(Base):
    __tablename__='game_event_jobs'
    __table_args__=(UniqueConstraint('event_id','user_id',name='uq_game_event_job_recipient'),)
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    event_id:Mapped[str]=mapped_column(ForeignKey('game_events.id'),nullable=False)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),nullable=False)
    status:Mapped[str]=mapped_column(String(16),default='pending',nullable=False,index=True)
    attempts:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    next_attempt_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False,index=True)
    lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    lease_token:Mapped[str|None]=mapped_column(String(64),nullable=True)
    error_code:Mapped[str|None]=mapped_column(String(64),nullable=True)
    sent_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)

class RemoteCommand(Base):
    __tablename__='remote_commands'
    __table_args__=(UniqueConstraint('user_id','idempotency_key',name='uq_command_user_key'),Index('ix_command_device_status','device_id','status'))
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    user_id:Mapped[int]=mapped_column(ForeignKey('users.id'),nullable=False)
    device_id:Mapped[str]=mapped_column(ForeignKey('devices.id'),nullable=False)
    idempotency_key:Mapped[str]=mapped_column(String(64),nullable=False)
    request_hash:Mapped[str]=mapped_column(String(64),nullable=False)
    command_type:Mapped[str]=mapped_column(String(32),nullable=False)
    payload:Mapped[str]=mapped_column(Text,nullable=False)
    status:Mapped[str]=mapped_column(String(16),nullable=False,default='PENDING')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
    expires_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    lease_hash:Mapped[str|None]=mapped_column(String(64),nullable=True)
    lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    next_attempt_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    attempts:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    acknowledged_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    result_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    error_code:Mapped[str|None]=mapped_column(String(64),nullable=True)
