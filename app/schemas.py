from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field

Platform = Literal["hassle", "radmir"]
Kind = Literal["sms", "calls", "ads", "queue", "system"]

class RegisterUser(BaseModel):
    telegram_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=64)

class PairingCreate(BaseModel):
    platform: Platform

class PairingConfirm(BaseModel):
    code: str
    telegram_id: int

class SettingUpdate(BaseModel):
    enabled: bool

class TicketCreate(BaseModel):
    request_id: UUID | None = None  # optional for legacy clients; bot always sends one
    category: Literal["connection", "license", "other"]
    message: str = Field(min_length=1, max_length=2000)
