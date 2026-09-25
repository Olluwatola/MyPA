"""LLM structured-output shapes for Notion classification — colocated together since
none of these map 1:1 onto a single persisted table (they're transient tool-use schemas,
converted into `core.notion.persistence.NotionPersistenceAction`s after the call
returns, not stored as-is). See `core/llm/notion_classification.py` (edit path) and
`core/llm/notion_initial_extraction.py` (initial-extraction chunked path).
"""

import uuid as uuid_pkg
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class NotionExtractedItem(BaseModel):
    """One date field for both kinds: for a goal, `due_date` is its target date (mapped to
    `Goal.target_date` in core/notion/persistence.py). `goal_ref`/`goal_link_confidence`
    apply to tasks only — the LLM's pick from the numbered open-goal list in its prompt."""

    item_type: Literal["task", "goal"]
    title: str
    description: str | None = None
    due_date: date | None = None
    urgency: Literal["low", "medium", "high"] = "medium"
    effort_level: Literal["deep_focus", "light_focus", "passive"] | None = None
    horizon: Literal["short_term", "long_term"] | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    goal_ref: int | None = None
    goal_link_confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None


# -------------- edit-path (one call per changed block) --------------
class NotionFreshClassificationResult(BaseModel):
    """Used when the block has no existing `notion_block_link` rows — classified from
    scratch into one of three outcomes (see PRD §6.5)."""

    outcome: Literal["not_actionable", "actionable", "insufficient_context"]
    summary: str
    items: list[NotionExtractedItem] = Field(default_factory=list)


class NotionAnchoredItemOutcome(BaseModel):
    item_id: uuid_pkg.UUID
    disposition: Literal["unchanged", "updated", "no_longer_applies"]
    updated_title: str | None = None
    updated_description: str | None = None
    updated_urgency: Literal["low", "medium", "high"] | None = None
    updated_effort_level: Literal["deep_focus", "light_focus", "passive"] | None = None


class NotionAnchoredClassificationResult(BaseModel):
    """Used when the block already has >=1 linked items — NOT reclassified from scratch.
    Must return exactly one entry in `existing_items` per currently-linked item it was
    shown (see the anchored-prompt assembly in `core/notion/edit_gate.py`)."""

    summary: str
    existing_items: list[NotionAnchoredItemOutcome] = Field(default_factory=list)
    additional_items: list[NotionExtractedItem] = Field(default_factory=list)
    insufficient_context: bool = False


# -------------- initial-extraction (chunked, one call per chunk) --------------
class NotionChunkExtractedItem(NotionExtractedItem):
    source_block_id: str  # which block in the chunk's in-scope window this item came from


class NotionChunkExtractionResult(BaseModel):
    """No three-way outcome / insufficient-context here — clarification escalation is
    scoped to the edit path only (a deliberate, stated scope line, not an oversight). A
    chunk just returns zero or more confidence-scored items, gated by persistence exactly
    like `run_memory_extraction_pipeline`'s existing below-threshold-drop behavior."""

    items: list[NotionChunkExtractedItem] = Field(default_factory=list)


# -------------- clarification resolution (Telegram reply/tap) --------------
class NotionClarificationResolution(BaseModel):
    matched_existing_goal_id: uuid_pkg.UUID | None = None
    new_item: NotionExtractedItem | None = None
