from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class NotionConnection(Base, UUIDMixin, TimestampMixin):
    """1:1 user <-> Notion OAuth grant. Unlike `TelegramLink`'s single shared bot token,
    Notion issues one access token per connecting user — `access_token` is Fernet
    ciphertext (see core/crypto.py), same treatment as Google's per-user tokens. No
    `SoftDeleteMixin` — disconnect is a plain nullable `revoked_at`, matching every other
    connection-style model in this codebase.

    `DateTime(timezone=True)` is explicit on every datetime column below — confirmed via
    a real local-Postgres round-trip (see the Feature 1.7 verification notes) that a bare
    `Mapped[datetime]` defaults to a naive `TIMESTAMP` on the SQLAlchemy/asyncpg side even
    though the migration creates the underlying column as `timestamptz`, which then
    raises at insert time for the tz-aware `datetime.now(UTC)` values this codebase always
    writes. `TimestampMixin`'s own `created_at`/`updated_at` already do this explicitly."""

    __tablename__ = "notion_connection"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    access_token: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    workspace_name: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
