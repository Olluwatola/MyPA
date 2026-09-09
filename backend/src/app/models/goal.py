import uuid as uuid_pkg
from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class Goal(Base, UUIDMixin, TimestampMixin):
    """Mirrors `models/task.py`'s shape minus `effort_level`/`urgency`/
    `urgency_manually_set`/`scheduled_event_id` (none apply to a goal), plus goal-only
    `horizon`/`target_date`. No sticky-override field — nothing here ever re-classifies
    an existing `Goal` (see decisions-log.md)."""

    __tablename__ = "goals"

    user_id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(20))  # manual | conversation | email | calendar | notion

    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | done

    memory_record_id: Mapped[uuid_pkg.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_extraction_record.id", ondelete="SET NULL"), nullable=True, default=None
    )
    horizon: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)  # short_term | long_term
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
