import uuid as uuid_pkg
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_serializer
from pydantic.json_schema import SkipJsonSchema

from ..core.schemas import TimestampSchema, UUIDSchema


# -------------- extraction result shapes (LLM structured output) --------------
class ExtractedEntity(BaseModel):
    """Persisted for Phase 2 (graph reasoning) — not read by anything in Phase 1."""

    name: str
    type: str


class ExtractedRelationship(BaseModel):
    """Persisted for Phase 2 — not read by anything in Phase 1."""

    subject: str
    predicate: str
    object: str


class ExtractedGoal(BaseModel):
    """A candidate goal from a single extraction run. Candidates from conversation/email
    (never calendar) at or above `settings.CONFIDENCE_THRESHOLD` become real `Goal` rows,
    after near-duplicate dedup; everything else stays only in the persisted record's
    `goals` JSONB until Feature 1.11 (see extraction.py)."""

    title: str
    description: str | None = None
    horizon: Literal["short_term", "long_term"] | None = None
    target_date: date | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class ExtractedPreference(BaseModel):
    """Persisted for Phase 2 — not read by anything in Phase 1."""

    category: str
    detail: str


class ExtractedTaskCandidate(BaseModel):
    """A candidate task from a single extraction run. Only candidates at or above
    `settings.CONFIDENCE_THRESHOLD` get promoted to a real `Task` row — everything else
    stays only in the persisted record's `tasks` JSONB (see extraction.py)."""

    title: str
    description: str | None = None
    due_date: date | None = None
    urgency: Literal["low", "medium", "high"] = "medium"
    effort_level: Literal["deep_focus", "light_focus", "passive"] | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    # The LLM's pick from the numbered open-goal list in its prompt, and how sure it is.
    goal_ref: int | None = None
    goal_link_confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    # Set by code from `goal_ref` (core/goals/context.py::resolve_goal_link), never by the
    # LLM — hidden from the tool schema.
    goal_id: SkipJsonSchema[uuid_pkg.UUID | None] = None


class MemoryExtractionResult(BaseModel):
    """The top-level extraction shape. `.model_json_schema()` becomes the
    `LlmProviderResponseFormat.schema_` passed into `run_with_validation_retry`."""

    summary: str
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    goals: list[ExtractedGoal] = Field(default_factory=list)
    preferences: list[ExtractedPreference] = Field(default_factory=list)
    tasks: list[ExtractedTaskCandidate] = Field(default_factory=list)


# -------------- persisted record shapes --------------
class MemoryExtractionRecordBase(BaseModel):
    user_id: uuid_pkg.UUID
    source_type: Literal["conversation", "email", "calendar", "notion"]
    summary: str

    # nullable — only meaningful for source_type == "conversation"
    source_channel: Literal["in_app", "telegram"] | None = None

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    goals: list[ExtractedGoal] = Field(default_factory=list)
    preferences: list[ExtractedPreference] = Field(default_factory=list)
    tasks: list[ExtractedTaskCandidate] = Field(default_factory=list)

    @field_serializer("entities", "relationships", "goals", "preferences", "tasks")
    def serialize_jsonb_items(self, items: list[BaseModel]) -> list[dict[str, Any]]:
        """These lists land in JSONB columns. FastCRUD's `create()` dumps in Python mode,
        which would leave `date`/`UUID` objects inside the JSON and crash SQLAlchemy's JSON
        encoder (known debt D-08) — so each item is always dumped in JSON mode."""
        return [item.model_dump(mode="json") for item in items]


class MemoryExtractionRecordCreate(MemoryExtractionRecordBase):
    """Append-only — created internally by the extraction pipeline, never posted
    directly by a client. Reused for FastCRUD's Update/UpdateInternal/Delete generic
    slots too (same trick as `TokenBlacklistUpdate`): nothing in this slice ever updates
    or deletes a record."""


class MemoryExtractionRecordRead(TimestampSchema, MemoryExtractionRecordBase, UUIDSchema):
    pass
