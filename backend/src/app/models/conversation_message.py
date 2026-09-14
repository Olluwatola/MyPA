from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class ConversationMessage(Base, UUIDMixin, TimestampMixin):
    """Raw per-turn chat text, auto-expiring after `CONVERSATION_MESSAGE_RETENTION`
    (core/llm/conversation.py) — this table exists because Telegram's Bot API is
    push-only (no `getChatHistory` equivalent). Summarized memory from extraction
    survives indefinitely regardless; only this verbatim text expires.

    A second, standalone index on `created_at` (below) is purely for the cleanup cron's
    unscoped scan — no composite `(user_id, created_at)` index, since the 7-day
    auto-expiry keeps per-user row counts small enough that this would be
    over-engineering."""

    __tablename__ = "conversation_message"
    __table_args__ = (Index("ix_conversation_message_created_at", "created_at"),)

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    channel: Mapped[str] = mapped_column(String(20))  # in_app | telegram
    content: Mapped[str] = mapped_column(Text)
