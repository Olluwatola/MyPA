"""The memory-extraction pipeline orchestrator.

Extraction uses the `high` tier — matches the reference's own choice for its closest
analog (per-chunk knowledge extraction), and MyPA's extraction accuracy directly drives
real task creation, so it warrants the best-available tier by default.
"""

import uuid as uuid_pkg
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...crud.crud_embeddings import crud_embeddings
from ...crud.crud_memory_extraction_records import crud_memory_extraction_records
from ...crud.crud_tasks import crud_tasks
from ...schemas.embedding import EmbeddingCreate
from ...schemas.memory_extraction_record import (
    MemoryExtractionRecordCreate,
    MemoryExtractionRecordRead,
    MemoryExtractionResult,
)
from ...schemas.task import TaskCreateInternal
from ..config import settings
from . import service
from .embedding_model import embed_text
from .provider import LlmMessage, LlmProviderResponseFormat
from .validation_retry import run_with_validation_retry

SYSTEM_PROMPT = (
    "You extract structured memory from a single piece of user content for a personal "
    "assistant app. Score each candidate task's confidence honestly — reserve high confidence "
    "(>= 0.7) for unambiguous commitments with a clear owner/due date; use lower confidence for "
    "vague or possibly-not-actionable mentions."
)

EXTRACTION_RESPONSE_FORMAT = LlmProviderResponseFormat(
    name="record_memory_extraction",
    schema_=MemoryExtractionResult.model_json_schema(),
)


async def call_extraction_llm(content: str) -> MemoryExtractionResult:
    assert service.llm_service is not None, "llm_service not initialized — call build_llm_service() at startup first."
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
) -> dict[str, Any]:
    result = await call_extraction_llm(content)

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

        embedding_vector = await embed_text(result.summary)
        await crud_embeddings.create(
            db=db,
            object=EmbeddingCreate(memory_record_id=record["id"], embedding=embedding_vector),
            commit=False,
        )

        # Low/medium-confidence candidates are not silently dropped or auto-created — they
        # stay only in the persisted record's `tasks` JSONB above; nothing promotes them to
        # a real `Task` row yet (no interrupt/confirm mechanism exists — Feature 1.11, later).
        for candidate in result.tasks:
            if candidate.confidence >= settings.CONFIDENCE_THRESHOLD:
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
                    ),
                    commit=False,
                )
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    return record
