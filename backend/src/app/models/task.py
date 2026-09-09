import uuid as uuid_pkg
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import TimestampMixin, UUIDMixin


class Task(Base, UUIDMixin, TimestampMixin):
    """`urgency_manually_set` is the sticky-override flag: once a user corrects
    `urgency`, later re-classification passes must not silently overwrite it (see
    decisions-log.md). `memory_record_id` is nullable — a manually-created task has no
    extraction record behind it."""

    __tablename__ = "tasks"

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
    # Set when a Free-Time Scouring suggestion is accepted — not wired this slice.
    scheduled_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    effort_level: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)

    urgency: Mapped[str] = mapped_column(String(10), default="medium")  # low | medium | high
    urgency_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
