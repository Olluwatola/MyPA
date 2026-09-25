import uuid as uuid_pkg
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db.database import Base
from ..core.db.models import SoftDeleteMixin, TimestampMixin, UUIDMixin


class Goal(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Mirrors `models/task.py`'s shape minus the task-only fields (`urgency`,
    `effort_level`, `scheduled_event_id`), plus goal-only `horizon`/`target_date`. A goal
    has one date, `target_date` (`due_date` was dropped in 1.9, decisions-log.md 2026-09-24).

    `title_manually_set`/`description_manually_set` are sticky-override flags: once a user
    edits that field in the app, Notion re-classification and dedup fill-blanks never
    change it again (core/items/sticky.py).

    Status is `open | paused | done | dropped`. Paused and dropped goals are left out of
    reasoning (chat context, AI task linking, goal resolution) — see core/goals/context.py.

    Soft-deleted (`is_deleted`/`deleted_at`). FastCRUD never filters these itself, so every
    read must pass `is_deleted=False` — except the Notion anchored prompt, Notion
    persistence/completion sync, the dedup pool and the activity check, which see deleted
    goals on purpose (see the 1.9 plan's read-path table)."""

    __tablename__ = "goals"

    user_id: Mapped[uuid_pkg.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(20))  # manual | conversation | email | calendar | notion

    description: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | paused | done | dropped

    memory_record_id: Mapped[uuid_pkg.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_extraction_record.id", ondelete="SET NULL"), nullable=True, default=None
    )
    horizon: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)  # short_term | long_term
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)

    title_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
    description_manually_set: Mapped[bool] = mapped_column(Boolean, default=False)
