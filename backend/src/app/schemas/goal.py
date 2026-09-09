import uuid as uuid_pkg
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.schemas import TimestampSchema, UUIDSchema

GoalSource = Literal["manual", "conversation", "email", "calendar", "notion"]
GoalStatus = Literal["open", "done"]
GoalHorizon = Literal["short_term", "long_term"]


class GoalBase(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    due_date: date | None = None
    horizon: GoalHorizon | None = None
    target_date: date | None = None


class Goal(TimestampSchema, GoalBase, UUIDSchema):
    """Full internal shape — never returned directly from a route."""

    user_id: uuid_pkg.UUID
    source: GoalSource
    status: GoalStatus = "open"
    memory_record_id: uuid_pkg.UUID | None = None


class GoalRead(BaseModel):
    id: uuid_pkg.UUID
    title: str
    description: str | None = None
    due_date: date | None = None
    status: GoalStatus
    source: GoalSource
    horizon: GoalHorizon | None = None
    target_date: date | None = None
    memory_record_id: uuid_pkg.UUID | None = None
    created_at: datetime


class GoalCreate(GoalBase):
    """Public input for manual goal creation — not routed this slice. `source` is
    server-set, never client-supplied."""

    model_config = ConfigDict(extra="forbid")


class GoalCreateInternal(GoalBase):
    user_id: uuid_pkg.UUID
    source: GoalSource
    memory_record_id: uuid_pkg.UUID | None = None


class GoalUpdate(BaseModel):
    """Defined for FastCRUD's generic signature — not routed this slice."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str | None, Field(min_length=1, max_length=255, default=None)]
    description: str | None = None
    due_date: date | None = None
    status: GoalStatus | None = None
    horizon: GoalHorizon | None = None
    target_date: date | None = None


class GoalUpdateInternal(GoalUpdate):
    updated_at: datetime


class GoalDelete(BaseModel):
    """Stub — hard-delete only (no SoftDeleteMixin on goals), not routed this slice."""

    model_config = ConfigDict(extra="forbid")


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
