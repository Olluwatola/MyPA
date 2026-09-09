"""Tests the pipeline orchestration in extraction.py: record persistence, embedding
generation, and confidence-gated task creation — mocked at the CRUD/LLM/embedding
boundary (the LLM adapters and the real DB are exercised elsewhere / manually)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.app.core.llm import extraction
from src.app.schemas.memory_extraction_record import ExtractedTaskCandidate, MemoryExtractionResult


def make_result(tasks: list[ExtractedTaskCandidate]) -> MemoryExtractionResult:
    return MemoryExtractionResult(summary="Buy milk and call mom", tasks=tasks)


class TestRunMemoryExtractionPipeline:
    @pytest.mark.asyncio
    async def test_persists_record_and_embedding_no_tasks(self, mock_db):
        user_id = uuid4()
        record_id = uuid4()

        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
            patch.object(
                extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id})
            ) as mock_record_create,
            patch.object(extraction.crud_embeddings, "create", AsyncMock()) as mock_embed_create,
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
        ):
            record = await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=user_id, source_type="conversation", source_channel="in_app", content="Buy milk"
            )

        assert record == {"id": record_id}
        mock_embed_create.assert_called_once()
        mock_task_create.assert_not_called()

        # every write goes through with commit=False; a single commit() at the end is
        # what actually makes the record/embedding/tasks one atomic transaction.
        assert mock_record_create.call_args.kwargs["commit"] is False
        assert mock_embed_create.call_args.kwargs["commit"] is False
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_partway_through_rolls_back_instead_of_partial_commit(self, mock_db):
        user_id = uuid4()
        record_id = uuid4()
        candidate = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)

        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([candidate]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
            patch.object(
                extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id})
            ),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()),
            patch.object(extraction.crud_tasks, "create", AsyncMock(side_effect=RuntimeError("db exploded"))),
        ):
            with pytest.raises(RuntimeError, match="db exploded"):
                await extraction.run_memory_extraction_pipeline(
                    db=mock_db,
                    user_id=user_id,
                    source_type="conversation",
                    source_channel="in_app",
                    content="Send invoice",
                )

        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_high_confidence_candidate_is_promoted_to_a_real_task(self, mock_db):
        user_id = uuid4()
        record_id = uuid4()
        candidate = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)

        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([candidate]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
            patch.object(
                extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id})
            ),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()),
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db,
                user_id=user_id,
                source_type="conversation",
                source_channel="in_app",
                content="Send invoice",
            )

        mock_task_create.assert_called_once()
        created_task = mock_task_create.call_args.kwargs["object"]
        assert created_task.title == "Send invoice"
        assert created_task.memory_record_id == record_id
        assert created_task.user_id == user_id

    @pytest.mark.asyncio
    async def test_low_confidence_candidate_is_not_promoted(self, mock_db):
        user_id = uuid4()
        record_id = uuid4()
        candidate = ExtractedTaskCandidate(title="Maybe call someone", confidence=0.3)

        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([candidate]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
            patch.object(
                extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id})
            ),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()),
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db,
                user_id=user_id,
                source_type="conversation",
                source_channel="in_app",
                content="Maybe call",
            )

        mock_task_create.assert_not_called()
