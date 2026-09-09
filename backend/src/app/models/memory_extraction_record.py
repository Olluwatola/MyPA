import uuid as uuid_pkg

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class MemoryExtractionRecord(Base, UUIDMixin, TimestampMixin):
    """Append-only — one row per extraction pipeline run. `entities`/`relationships`/
    `goals`/`preferences` are persisted for Phase 2 (graph reasoning) but not read by
    anything in Phase 1; `tasks` is actively used to drive real `Task` row creation."""

    __tablename__ = "memory_extraction_record"

    user_id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(20))  # conversation | email | calendar | notion
    summary: Mapped[str] = mapped_column(Text)

    # nullable — only meaningful for source_type == "conversation" (in_app | telegram)
    source_channel: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)

    entities: Mapped[list] = mapped_column(JSONB, default_factory=list)
    relationships: Mapped[list] = mapped_column(JSONB, default_factory=list)
    goals: Mapped[list] = mapped_column(JSONB, default_factory=list)
    preferences: Mapped[list] = mapped_column(JSONB, default_factory=list)
    tasks: Mapped[list] = mapped_column(JSONB, default_factory=list)
