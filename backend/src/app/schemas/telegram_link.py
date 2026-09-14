import uuid as uuid_pkg
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ..core.schemas import TimestampSchema, UUIDSchema


class TelegramLinkBase(BaseModel):
    user_id: uuid_pkg.UUID
    telegram_chat_id: int
    linked_at: datetime


class TelegramLink(TimestampSchema, TelegramLinkBase, UUIDSchema):
    """Full internal shape — never returned directly from a route."""

    consecutive_failure_count: int = 0
    last_failure_at: datetime | None = None


class TelegramLinkRead(BaseModel):
    """Public response shape — deliberately omits `telegram_chat_id` (Telegram's
    internal chat identifier, not something a client needs back)."""

    id: uuid_pkg.UUID
    linked_at: datetime
    created_at: datetime


class TelegramLinkCreateInternal(TelegramLinkBase):
    """Created only from the inbound `/start <token>` webhook branch — never posted
    directly by a client."""


class TelegramLinkUpdate(BaseModel):
    """Stub — defined for FastCRUD's generic signature; not routed this slice."""

    model_config = ConfigDict(extra="forbid")


class TelegramLinkUpdateInternal(BaseModel):
    """Internal update fields — used by the re-link upsert and by the outbound send
    job's channel-health column updates."""

    telegram_chat_id: int | None = None
    linked_at: datetime | None = None
    consecutive_failure_count: int | None = None
    last_failure_at: datetime | None = None


class TelegramLinkDelete(BaseModel):
    """Stub — unlink uses `db_delete` directly (see api/v1/telegram_link.py), never a
    FastCRUD generic delete call."""

    model_config = ConfigDict(extra="forbid")


class TelegramLinkUrlRead(BaseModel):
    """Response shape for `GET /telegram/link`."""

    deep_link_url: str


class TelegramUnlinkRead(BaseModel):
    """Response shape for `DELETE /telegram/link`."""

    status: str
