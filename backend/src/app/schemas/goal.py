import uuid as uuid_pkg
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema

GoalSource = Literal["manual", "conversation", "email", "calendar", "notion"]
GoalStatus = Literal["open", "paused", "done", "dropped"]
GoalHorizon = Literal["short_term", "long_term"]


class GoalBase(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    horizon: GoalHorizon | None = None
    target_date: date | None = None


class Goal(TimestampSchema, GoalBase, UUIDSchema, PersistentDeletion):
    """Full internal shape — never returned directly from a route."""

    user_id: uuid_pkg.UUID
    source: GoalSource
    status: GoalStatus = "open"
    memory_record_id: uuid_pkg.UUID | None = None
    title_manually_set: bool = False
    description_manually_set: bool = False


class GoalRead(BaseModel):
    id: uuid_pkg.UUID
    title: str
    description: str | None = None
    status: GoalStatus
    source: GoalSource
    horizon: GoalHorizon | None = None
    target_date: date | None = None
    memory_record_id: uuid_pkg.UUID | None = None
    created_at: datetime


class GoalCreate(GoalBase):
    """Public input for `POST /goals`. `horizon: None` means "left empty — let the AI guess
    in the background" (core/goals/jobs.py). `source` is server-set (`"manual"`), never
    client-supplied."""

    model_config = ConfigDict(extra="forbid")


class GoalCreateInternal(GoalBase):
    user_id: uuid_pkg.UUID
    source: GoalSource
    memory_record_id: uuid_pkg.UUID | None = None


class GoalUpdate(BaseModel):
    """Public input for `PATCH /goals/{id}`. `status` is deliberately absent — it changes
    only through `PATCH /goals/{id}/status`, the one place that enqueues Notion sync. An
    explicit `null` clears `description`/`horizon`/`target_date`, but is rejected for the
    non-nullable `title`."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=1, max_length=255, default=None)]
    description: str | None = None
    horizon: GoalHorizon | None = None
    target_date: date | None = None

    @model_validator(mode="after")
    def reject_null_title(self) -> "GoalUpdate":
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        return self


class GoalUpdateInternal(GoalUpdate):
    updated_at: datetime
    # Sticky-override flags, set alongside a user edit of the matching field (see
    # core/items/sticky.py). Never instantiated — internal `.update()` calls pass a plain
    # dict (decisions-log.md, 2026-09-09).
    title_manually_set: bool | None = None
    description_manually_set: bool | None = None


class GoalDelete(BaseModel):
    """Defined for FastCRUD's generic signature. `crud_goals.delete()` is a soft delete
    (goals carry `is_deleted`/`deleted_at`)."""

    model_config = ConfigDict(extra="forbid")


class GoalDeletedRead(BaseModel):
    """Response shape for `DELETE /goals/{id}`."""

    message: str


class GoalHorizonGuess(BaseModel):
    """LLM structured output for the manual-create horizon guess (core/goals/jobs.py)."""

    horizon: GoalHorizon | None = None


# -------------- onboarding goal-suggestion shapes --------------
class SuggestedGoal(BaseModel):
    """The one canonical shape for: the synthesis LLM's structured output, the JSONB
    persisted on `users.onboarding_suggested_goals`, and what the client posts to
    `POST /onboarding/goals`."""

    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    horizon: GoalHorizon | None = None


class GoalSynthesisResult(BaseModel):
    suggested_goals: list[SuggestedGoal] = Field(default_factory=list)
