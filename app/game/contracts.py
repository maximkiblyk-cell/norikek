"""Contracts only: no game events are read and no commands are executed here."""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, AsyncIterator, Mapping, Protocol
from uuid import UUID

class Platform(StrEnum):
    HASSLE = 'hassle'
    RADMIR = 'radmir'

class EventType(StrEnum):
    SMS = 'sms'
    INCOMING_CALL = 'incoming_call'
    QUEUE_UPDATE = 'queue_update'
    ADVERTISEMENT = 'advertisement'
    GAME_STATE = 'game_state'
    ITEM_DATA = 'item_data'

class CommandStatus(StrEnum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    SENT = 'sent'
    FAILED = 'failed'
    EXPIRED = 'expired'

@dataclass(frozen=True)
class GameEvent:
    event_id: UUID
    device_id: UUID
    platform: Platform
    occurred_at: datetime
    event_type: EventType
    payload: Mapping[str, Any]
    schema_version: int = 1
    # Server derives user and delivery state from trusted credentials, not event payload.

@dataclass(frozen=True)
class GameCommand:
    command_id: UUID
    device_id: UUID
    platform: Platform
    kind: str
    payload: Mapping[str, Any]
    expires_at: datetime

@dataclass(frozen=True)
class CommandReceipt:
    command_id: UUID
    status: CommandStatus
    # SENT is only valid after actual confirmation from an authorized game interface.
    confirmed_at: datetime | None = None
    error_code: str | None = None

class GameAdapter(Protocol):
    @property
    def enabled(self) -> bool: ...
    def status(self) -> dict[str, Any]: ...
    def events(self) -> AsyncIterator[GameEvent]: ...
    async def execute(self, command: GameCommand) -> CommandReceipt: ...

class AdapterUnavailable(RuntimeError):
    pass
