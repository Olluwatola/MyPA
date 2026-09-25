import uuid as uuid_pkg
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import SoftDeleteMixin, TimestampMixin, UUIDMixin


class Task(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """The five `*_manually_set` columns are sticky-override flags, one per field: once a
    user edits that field, no automated path (Notion re-classification, dedup fill-blanks,
    the manual-create AI guess job) may overwrite it (see decisions-log.md, 2026-09-24).
    `memory_record_id` is nullable — a manually-created task has no extraction record
    behind it.

    `goal_id` is one optional pointer to the goal this task serves — set by the user, or
    by the AI when it creates a task and is confident. Deliberately not a graph and no
    `relationship()` (PRD §3: "LLM-inferred, not graph"). Soft-deleting a goal clears it
    here (api/v1/goals.py); the FK's `ON DELETE SET NULL` only covers a hard delete.

    Soft-deleted (`is_deleted`/`deleted_at`). FastCRUD never filters these itself, so
    every read must pass `is_deleted=False` — except the Notion paths and the dedup pool
    query, which see deleted tasks on purpose (`core/notion/`, `core/tasks/dedup.py`)."""

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
    effort_level_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
    title_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
    description_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)

    goal_id: Mapped[uuid_pkg.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="SET NULL"), nullable=True, default=None, index=True
    )
    goal_id_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
