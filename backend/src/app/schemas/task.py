import uuid as uuid_pkg
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema

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


class Task(TimestampSchema, TaskBase, UUIDSchema, PersistentDeletion):
    """Full internal shape — never returned directly from a route."""

    user_id: uuid_pkg.UUID
    source: TaskSource
    status: TaskStatus = "open"
    memory_record_id: uuid_pkg.UUID | None = None
    scheduled_event_id: str | None = None
    urgency_manually_set: bool = False
    effort_level_manually_set: bool = False
    title_manually_set: bool = False
    description_manually_set: bool = False
    goal_id: uuid_pkg.UUID | None = None
    goal_id_manually_set: bool = False


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
    goal_id: uuid_pkg.UUID | None = None
    created_at: datetime


class TaskCreate(BaseModel):
    """Public input for `POST /tasks`. Deliberately does not inherit `TaskBase`: `None`
    for `urgency`/`effort_level` means "left empty — let the AI guess in the background",
    which `TaskBase`'s `"medium"` default can't express. `source` is server-set
    (`"manual"`), never client-supplied. `goal_id` must be one of the user's own
    non-deleted goals."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    due_date: date | None = None
    urgency: Urgency | None = None
    effort_level: EffortLevel | None = None
    goal_id: uuid_pkg.UUID | None = None


class TaskCreateInternal(TaskBase):
    user_id: uuid_pkg.UUID
    source: TaskSource
    memory_record_id: uuid_pkg.UUID | None = None
    urgency_manually_set: bool = False
    effort_level_manually_set: bool = False
    goal_id: uuid_pkg.UUID | None = None
    goal_id_manually_set: bool = False


class TaskUpdate(BaseModel):
    """Public input for `PATCH /tasks/{id}`. `status` is deliberately absent — it changes
    only through `PATCH /tasks/{id}/status`, the one place that enqueues Notion sync.
    An explicit `null` clears `description`/`due_date`/`effort_level` and unlinks
    `goal_id`, but is rejected for the non-nullable `title`/`urgency`."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=1, max_length=255, default=None)]
    description: str | None = None
    due_date: date | None = None
    urgency: Urgency | None = None
    effort_level: EffortLevel | None = None
    goal_id: uuid_pkg.UUID | None = None

    @model_validator(mode="after")
    def reject_null_for_required_fields(self) -> "TaskUpdate":
        for field in ("title", "urgency"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TaskUpdateInternal(TaskUpdate):
    updated_at: datetime
    # Sticky-override flags, set alongside a user edit of the matching field (see
    # core/items/sticky.py). Never instantiated — internal `.update()` calls pass a plain
    # dict (decisions-log.md, 2026-09-09).
    urgency_manually_set: bool | None = None
    effort_level_manually_set: bool | None = None
    title_manually_set: bool | None = None
    description_manually_set: bool | None = None
    goal_id_manually_set: bool | None = None


class TaskDelete(BaseModel):
    """Defined for FastCRUD's generic signature. `crud_tasks.delete()` is a soft delete
    (tasks carry `is_deleted`/`deleted_at`)."""

    model_config = ConfigDict(extra="forbid")


class TaskDeletedRead(BaseModel):
    """Response shape for `DELETE /tasks/{id}`."""

    message: str


class TaskFieldGuess(BaseModel):
    """LLM structured output for the manual-create guess job — only the requested
    field(s) are used (core/tasks/jobs.py)."""

    urgency: Urgency | None = None
    effort_level: EffortLevel | None = None
