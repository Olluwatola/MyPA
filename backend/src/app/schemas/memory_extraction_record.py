import uuid as uuid_pkg
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field

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
    """Persisted for Phase 2 — not promoted to a real `Goal` row this slice (`goals`
    table is out of scope for Feature 1.3)."""

    title: str
    description: str | None = None
    horizon: Literal["short_term", "long_term"] | None = None


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


class MemoryExtractionRecordCreate(MemoryExtractionRecordBase):
    """Append-only — created internally by the extraction pipeline, never posted
    directly by a client. Reused for FastCRUD's Update/UpdateInternal/Delete generic
    slots too (same trick as `TokenBlacklistUpdate`): nothing in this slice ever updates
    or deletes a record."""


class MemoryExtractionRecordRead(TimestampSchema, MemoryExtractionRecordBase, UUIDSchema):
    pass
