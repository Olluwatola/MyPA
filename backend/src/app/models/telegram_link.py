from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class TelegramLink(Base, UUIDMixin, TimestampMixin):
    """1:1 user <-> Telegram chat mapping for the single shared Bot API bot. No
    `revoked_at` column (deliberate, unlike `IntegrationConnection`) — unlinking hard-
    deletes the row instead of soft-revoking it (see api/v1/telegram_link.py)."""

    __tablename__ = "telegram_link"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    linked_at: Mapped[datetime]

    # Channel-health signal, updated by the outbound send job (core/telegram/jobs.py) —
    # incremented on failure, reset on success. No "surfaced in-app" UI yet.
    consecutive_failure_count: Mapped[int] = mapped_column(default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
