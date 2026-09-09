import uuid as uuid_pkg
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema, UUIDSchema

Urgency = Literal["low", "medium", "high"]
EffortLevel = Literal["deep_focus", "light_focus", "passive"]
TaskSource = Literal["manual", "conversation", "email", "calendar", "notion"]
TaskStatus = Literal["open", "done"]


class TaskBase(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    due_date: date | None = None
    urgency: Urgency = "medium"
    effort_level: EffortLevel | None = None


class Task(TimestampSchema, TaskBase, UUIDSchema):
    """Full internal shape — never returned directly from a route."""

    user_id: uuid_pkg.UUID
    source: TaskSource
    status: TaskStatus = "open"
    memory_record_id: uuid_pkg.UUID | None = None
    scheduled_event_id: str | None = None
    urgency_manually_set: bool = False


class TaskRead(BaseModel):
    id: uuid_pkg.UUID
    title: str
    description: str | None = None
    due_date: date | None = None
    status: TaskStatus
    source: TaskSource
    urgency: Urgency
    effort_level: EffortLevel | None = None
    memory_record_id: uuid_pkg.UUID | None = None
    scheduled_event_id: str | None = None
    created_at: datetime


class TaskCreate(TaskBase):
    """Public input for manual task creation — not routed this slice. `source` is
    server-set (`"manual"`), never client-supplied."""

    model_config = ConfigDict(extra="forbid")


class TaskCreateInternal(TaskBase):
    user_id: uuid_pkg.UUID
    source: TaskSource
    memory_record_id: uuid_pkg.UUID | None = None


class TaskUpdate(BaseModel):
    """Defined for FastCRUD's generic signature — not routed this slice."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=1, max_length=255, default=None)]
    description: str | None = None
    due_date: date | None = None
    status: TaskStatus | None = None
    urgency: Urgency | None = None
    effort_level: EffortLevel | None = None


class TaskUpdateInternal(TaskUpdate):
    updated_at: datetime
    # Set alongside a user-driven `urgency` change — the sticky-override flag a future
    # re-classification pass must check before silently overwriting `urgency` (see
    # decisions-log.md). Not read anywhere this slice — no re-classification pass exists yet.
    urgency_manually_set: bool | None = None


class TaskDelete(BaseModel):
    """Stub — hard-delete only (no SoftDeleteMixin on tasks), not routed this slice."""

    model_config = ConfigDict(extra="forbid")
