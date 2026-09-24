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


def _pass_through(db, user_id, candidates):
    """Stands in for dedup when a test isn't about dedup: every candidate is new."""
    return candidates


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
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
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
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
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
    async def test_embed_false_skips_embedding_step(self, mock_db):
        """Feature 1.4: calendar ingestion passes embed=False (no similarity-search need
        for event content) — every other existing call site keeps the embed=True
        default, unaffected."""
        user_id = uuid4()
        record_id = uuid4()

        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)) as mock_embed_text,
            patch.object(
                extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id})
            ),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()) as mock_embed_create,
            patch.object(extraction.crud_tasks, "create", AsyncMock()),
        ):
            record = await extraction.run_memory_extraction_pipeline(
                db=mock_db,
                user_id=user_id,
                source_type="calendar",
                source_channel=None,
                content="Team sync at 10am",
                embed=False,
            )

        assert record == {"id": record_id}
        mock_embed_text.assert_not_called()
        mock_embed_create.assert_not_called()
        mock_db.commit.assert_called_once()

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

    @pytest.mark.asyncio
    async def test_dedup_gets_only_confident_candidates_and_decides_what_is_created(self, mock_db):
        confident = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)
        duplicate = ExtractedTaskCandidate(title="Send the invoice", confidence=0.8)
        unsure = ExtractedTaskCandidate(title="Maybe call someone", confidence=0.3)

        with (
            patch.object(
                extraction, "call_extraction_llm", AsyncMock(return_value=make_result([confident, duplicate, unsure]))
            ),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
            patch.object(extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": uuid4()})),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()),
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
            patch.object(extraction, "resolve_candidates", AsyncMock(return_value=[confident])) as mock_resolve,
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=uuid4(), source_type="email", source_channel=None, content="Invoice email"
            )

        assert mock_resolve.call_args.args[2] == [confident, duplicate]
        mock_task_create.assert_called_once()
        assert mock_task_create.call_args.kwargs["object"].title == "Send invoice"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedup_failure_rolls_back(self, mock_db):
        candidate = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)
        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([candidate]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
            patch.object(extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": uuid4()})),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()),
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=RuntimeError("embedding failed"))),
        ):
            with pytest.raises(RuntimeError, match="embedding failed"):
                await extraction.run_memory_extraction_pipeline(
                    db=mock_db, user_id=uuid4(), source_type="email", source_channel=None, content="Invoice email"
                )

        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()
