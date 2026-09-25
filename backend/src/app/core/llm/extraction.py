"""The memory-extraction pipeline orchestrator.

Extraction uses the `high` tier — matches the reference's own choice for its closest
analog (per-chunk knowledge extraction), and MyPA's extraction accuracy directly drives
real task and goal creation, so it warrants the best-available tier by default.
"""

import uuid as uuid_pkg
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_embeddings import crud_embeddings
from ...crud.crud_goals import crud_goals
from ...crud.crud_memory_extraction_records import crud_memory_extraction_records
from ...crud.crud_tasks import crud_tasks
from ...schemas.embedding import EmbeddingCreate
from ...schemas.goal import GoalCreateInternal
from ...schemas.memory_extraction_record import (
    MemoryExtractionRecordCreate,
    MemoryExtractionRecordRead,
    MemoryExtractionResult,
)
from ...schemas.task import TaskCreateInternal
from ..config import settings
from ..goals.context import format_goals_for_prompt, load_open_goals, resolve_goal_link
from ..items.dedup import goal_dedup_spec, resolve_candidates, task_dedup_spec
from . import service
from .embedding_model import embed_text
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

# Goals are auto-created only from chat and email — never calendar (decisions-log.md
# 2026-09-24), and never from `POST /memory/ingest` with `source_type="notion"` (Notion
# goals come only through core/notion/persistence.py).
GOAL_SOURCE_TYPES = ("conversation", "email")

SYSTEM_PROMPT = (
    "You extract structured memory from a single piece of user content for a personal "
    "assistant app. Score each candidate task's confidence honestly — reserve high confidence "
    "(>= 0.7) for unambiguous commitments with a clear owner/due date; use lower confidence for "
    "vague or possibly-not-actionable mentions. Score each goal's confidence the same honest way — "
    "reserve >= 0.7 for a clearly stated, lasting aim the user holds, not a passing remark; set a "
    "goal's target_date only if a real date is stated. If the user's open goals are listed, do not "
    "extract a goal that is already on that list, and for each task set goal_ref to the number of "
    "the listed goal it clearly serves, with an honest goal_link_confidence; leave both empty if "
    "you're unsure, and never refer to a goal that isn't listed."
)

EXTRACTION_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="record_memory_extraction",
    schema_=MemoryExtractionResult.model_json_schema(),
)


async def call_extraction_llm(content: str, open_goals: list[dict[str, Any]]) -> MemoryExtractionResult:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
    if open_goals:
        content = f"{content}\n\nThe user's open goals:\n{format_goals_for_prompt(open_goals)}"
    return await run_with_validation_retry(
        llm_service=service.llm_service,
        tier="high",
        messages=[
            LlmMessage(role="system", content=SYSTEM_PROMPT),
            LlmMessage(role="user", content=content),
        ],
        response_format=EXTRACTION_RESPONSE_FORMAT,
        validate=MemoryExtractionResult.model_validate_json,
    )


async def run_memory_extraction_pipeline(
    db: AsyncSession,
    user_id: uuid_pkg.UUID,
    source_type: str,
    source_channel: str | None,
    content: str,
    embed: bool = True,
) -> dict[str, Any]:
    """`embed=False` skips the embedding step — used by calendar ingestion (no similarity
    search need for event content, see decisions-log.md). Every existing call site is
    unchanged by this default; only `process_calendar_webhook` passes `embed=False`."""
    # Loaded before the call: the prompt lists them so the AI can link a task to one.
    open_goals = await load_open_goals(db, user_id)
    result = await call_extraction_llm(content, open_goals)

    # Resolved before the record is written, so the stored `tasks` JSONB shows which
    # links were accepted. Unsure links are never saved (Feature 1.11 will ask).
    for candidate in result.tasks:
        candidate.goal_id = resolve_goal_link(candidate.goal_ref, candidate.goal_link_confidence, open_goals)

    # One transaction for every write below (all `commit=False`, one `db.commit()` at the
    # end) — otherwise a failure partway through (e.g. the 2nd of 3 task creates) would
    # leave earlier writes permanently committed while the caller sees the call as failed.
    try:
        record = await crud_memory_extraction_records.create(
            db=db,
            object=MemoryExtractionRecordCreate(
                user_id=user_id,
                source_type=source_type,  # type: ignore[arg-type]
                source_channel=source_channel,  # type: ignore[arg-type]
                summary=result.summary,
                entities=result.entities,
                relationships=result.relationships,
                goals=result.goals,
                preferences=result.preferences,
                tasks=result.tasks,
            ),
            schema_to_select=MemoryExtractionRecordRead,
            commit=False,
        )

        if embed:
            embedding_vector = await embed_text(result.summary)
            await crud_embeddings.create(
                db=db,
                object=EmbeddingCreate(memory_record_id=record["id"], embedding=embedding_vector),
                commit=False,
            )

        # Low/medium-confidence candidates are not silently dropped or auto-created — they
        # stay only in the persisted record's `tasks`/`goals` JSONB above; nothing promotes
        # them to a real row yet (no interrupt/confirm mechanism exists — Feature 1.11,
        # later). Confident ones go through near-duplicate dedup first (core/items/dedup.py),
        # whose fill-blank updates join this same transaction.
        if source_type in GOAL_SOURCE_TYPES:
            confident_goals = [goal for goal in result.goals if goal.confidence >= settings.CONFIDENCE_THRESHOLD]
            for goal in await resolve_candidates(db, goal_dedup_spec(), user_id, confident_goals):
                await crud_goals.create(
                    db=db,
                    object=GoalCreateInternal(
                        user_id=user_id,
                        title=goal.title,
                        description=goal.description,
                        horizon=goal.horizon,
                        target_date=goal.target_date,
                        source=source_type,  # type: ignore[arg-type]
                        memory_record_id=record["id"],
                    ),
                    commit=False,
                )

        confident = [candidate for candidate in result.tasks if candidate.confidence >= settings.CONFIDENCE_THRESHOLD]
        for candidate in await resolve_candidates(db, task_dedup_spec(), user_id, confident):
            await crud_tasks.create(
                db=db,
                object=TaskCreateInternal(
                    user_id=user_id,
                    title=candidate.title,
                    description=candidate.description,
                    due_date=candidate.due_date,
                    urgency=candidate.urgency,
                    effort_level=candidate.effort_level,
                    source=source_type,  # type: ignore[arg-type]
                    memory_record_id=record["id"],
                    # An AI link never sets goal_id_manually_set — only a user choice is sticky.
                    goal_id=candidate.goal_id,
                ),
                commit=False,
            )
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    return record
