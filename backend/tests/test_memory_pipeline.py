"""Tests the pipeline orchestration in extraction.py: record persistence, embedding
generation, confidence-gated task and goal creation, and the AI task -> goal link — mocked
at the CRUD/LLM/embedding boundary (the LLM adapters and the real DB are exercised
elsewhere / manually)."""

import json
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.app.core.llm import extraction
from src.app.schemas.memory_extraction_record import (
    ExtractedGoal,
    ExtractedTaskCandidate,
    MemoryExtractionRecordCreate,
    MemoryExtractionResult,
)


def make_result(
    tasks: list[ExtractedTaskCandidate], goals: list[ExtractedGoal] | None = None
) -> MemoryExtractionResult:
    return MemoryExtractionResult(summary="Buy milk and call mom", tasks=tasks, goals=goals or [])


def _pass_through(db, spec, user_id, candidates):
    """Stands in for dedup when a test isn't about dedup: every candidate is new."""
    return candidates


@pytest.fixture(autouse=True)
def no_open_goals():
    """Most tests don't care about goal linking — the user has no open goals."""
    with patch.object(extraction, "load_open_goals", AsyncMock(return_value=[])) as mock_load:
        yield mock_load


def _common_patches(result: MemoryExtractionResult, record_id=None):
    return (
        patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=result)),
        patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)),
        patch.object(
            extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id or uuid4()})
        ),
        patch.object(extraction.crud_embeddings, "create", AsyncMock()),
    )


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
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
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
        candidate = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)
        llm, embed, record, embedding = _common_patches(make_result([candidate]))

        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction.crud_tasks, "create", AsyncMock(side_effect=RuntimeError("db exploded"))),
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
        ):
            with pytest.raises(RuntimeError, match="db exploded"):
                await extraction.run_memory_extraction_pipeline(
                    db=mock_db, user_id=uuid4(), source_type="conversation", source_channel="in_app", content="x"
                )

        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_high_confidence_candidate_is_promoted_to_a_real_task(self, mock_db):
        user_id = uuid4()
        record_id = uuid4()
        candidate = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)
        llm, embed, record, embedding = _common_patches(make_result([candidate]), record_id)

        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=user_id, source_type="conversation", source_channel="in_app", content="x"
            )

        mock_task_create.assert_called_once()
        created_task = mock_task_create.call_args.kwargs["object"]
        assert created_task.title == "Send invoice"
        assert created_task.memory_record_id == record_id
        assert created_task.user_id == user_id
        assert created_task.goal_id is None

    @pytest.mark.asyncio
    async def test_embed_false_skips_embedding_step(self, mock_db):
        """Feature 1.4: calendar ingestion passes embed=False (no similarity-search need
        for event content) — every other existing call site keeps the embed=True
        default, unaffected."""
        record_id = uuid4()

        with (
            patch.object(extraction, "call_extraction_llm", AsyncMock(return_value=make_result([]))),
            patch.object(extraction, "embed_text", AsyncMock(return_value=[0.1] * 384)) as mock_embed_text,
            patch.object(
                extraction.crud_memory_extraction_records, "create", AsyncMock(return_value={"id": record_id})
            ),
            patch.object(extraction.crud_embeddings, "create", AsyncMock()) as mock_embed_create,
            patch.object(extraction.crud_tasks, "create", AsyncMock()),
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
        ):
            record = await extraction.run_memory_extraction_pipeline(
                db=mock_db,
                user_id=uuid4(),
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
        candidate = ExtractedTaskCandidate(title="Maybe call someone", confidence=0.3)
        llm, embed, record, embedding = _common_patches(make_result([candidate]))

        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=uuid4(), source_type="conversation", source_channel="in_app", content="x"
            )

        mock_task_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_gets_only_confident_candidates_and_decides_what_is_created(self, mock_db):
        confident = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)
        duplicate = ExtractedTaskCandidate(title="Send the invoice", confidence=0.8)
        unsure = ExtractedTaskCandidate(title="Maybe call someone", confidence=0.3)

        async def _resolve(db, spec, user_id, candidates):
            return [confident] if spec.label == "task" else candidates

        llm, embed, record, embedding = _common_patches(make_result([confident, duplicate, unsure]))
        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_resolve)) as mock_resolve,
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=uuid4(), source_type="email", source_channel=None, content="Invoice email"
            )

        task_call = next(c for c in mock_resolve.call_args_list if c.args[1].label == "task")
        assert task_call.args[3] == [confident, duplicate]
        mock_task_create.assert_called_once()
        assert mock_task_create.call_args.kwargs["object"].title == "Send invoice"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedup_failure_rolls_back(self, mock_db):
        candidate = ExtractedTaskCandidate(title="Send invoice", confidence=0.9)
        llm, embed, record, embedding = _common_patches(make_result([candidate]))
        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=RuntimeError("embedding failed"))),
        ):
            with pytest.raises(RuntimeError, match="embedding failed"):
                await extraction.run_memory_extraction_pipeline(
                    db=mock_db, user_id=uuid4(), source_type="email", source_channel=None, content="Invoice email"
                )

        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()


class TestGoalCreation:
    """Required proof (d), pipeline half: chat/email goals are confidence-gated and go
    through goal dedup; calendar never creates goals."""

    async def _run(self, mock_db, goals, source_type="email", resolve=_pass_through, record_id=None):
        llm, embed, record, embedding = _common_patches(make_result([], goals), record_id)
        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction.crud_goals, "create", AsyncMock()) as mock_goal_create,
            patch.object(extraction.crud_tasks, "create", AsyncMock()),
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=resolve)) as mock_resolve,
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=uuid4(), source_type=source_type, source_channel=None, content="x"
            )
        return mock_goal_create, mock_resolve

    @pytest.mark.asyncio
    async def test_confidence_gate_at_threshold(self, mock_db):
        at_bar = ExtractedGoal(title="Launch ClientPal", confidence=0.7, target_date=date(2027, 3, 1))
        below = ExtractedGoal(title="Maybe learn guitar", confidence=0.69)
        mock_goal_create, mock_resolve = await self._run(mock_db, [at_bar, below])

        goal_call = next(c for c in mock_resolve.call_args_list if c.args[1].label == "goal")
        assert goal_call.args[3] == [at_bar]
        created = mock_goal_create.call_args.kwargs["object"]
        assert created.title == "Launch ClientPal"
        assert created.source == "email"
        assert created.target_date == date(2027, 3, 1)
        assert mock_goal_create.call_args.kwargs["commit"] is False

    @pytest.mark.asyncio
    async def test_conversation_goals_get_conversation_source_and_record_link(self, mock_db):
        record_id = uuid4()
        mock_goal_create, _ = await self._run(
            mock_db, [ExtractedGoal(title="Run a marathon", confidence=0.9)], "conversation", record_id=record_id
        )
        created = mock_goal_create.call_args.kwargs["object"]
        assert created.source == "conversation"
        assert created.memory_record_id == record_id

    @pytest.mark.parametrize("source_type", ["calendar", "notion"])
    @pytest.mark.asyncio
    async def test_no_goals_from_calendar_or_notion(self, mock_db, source_type):
        mock_goal_create, mock_resolve = await self._run(
            mock_db, [ExtractedGoal(title="Launch ClientPal", confidence=0.95)], source_type
        )
        mock_goal_create.assert_not_called()
        assert all(c.args[1].label == "task" for c in mock_resolve.call_args_list)

    @pytest.mark.asyncio
    async def test_only_dedup_survivors_are_created(self, mock_db):
        goal = ExtractedGoal(title="Launch ClientPal", confidence=0.9)

        async def _resolve(db, spec, user_id, candidates):
            return [] if spec.label == "goal" else candidates

        mock_goal_create, _ = await self._run(mock_db, [goal], resolve=_resolve)
        mock_goal_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_goal_create_failure_rolls_back(self, mock_db):
        llm, embed, record, embedding = _common_patches(
            make_result([], [ExtractedGoal(title="Launch ClientPal", confidence=0.9)])
        )
        with (
            llm,
            embed,
            record,
            embedding,
            patch.object(extraction.crud_goals, "create", AsyncMock(side_effect=RuntimeError("boom"))),
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await extraction.run_memory_extraction_pipeline(
                    db=mock_db, user_id=uuid4(), source_type="email", source_channel=None, content="x"
                )
        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()


class TestTaskGoalLink:
    """Required proof (f), extraction half: the AI links a task to an open goal only when
    confident, and only to a goal it was shown."""

    GOALS = [
        {"id": uuid4(), "title": "Launch ClientPal", "description": None, "horizon": "short_term"},
        {"id": uuid4(), "title": "Run a marathon", "description": None, "horizon": None},
    ]

    async def _created_task(self, mock_db, candidate, goals):
        llm, embed, record, embedding = _common_patches(make_result([candidate]))
        with (
            patch.object(extraction, "load_open_goals", AsyncMock(return_value=goals)),
            llm as mock_llm,
            embed,
            record as mock_record_create,
            embedding,
            patch.object(extraction.crud_tasks, "create", AsyncMock()) as mock_task_create,
            patch.object(extraction, "resolve_candidates", AsyncMock(side_effect=_pass_through)),
        ):
            await extraction.run_memory_extraction_pipeline(
                db=mock_db, user_id=uuid4(), source_type="email", source_channel=None, content="x"
            )
        return mock_task_create.call_args.kwargs["object"], mock_llm, mock_record_create

    @pytest.mark.asyncio
    async def test_confident_link_is_saved(self, mock_db):
        candidate = ExtractedTaskCandidate(
            title="Draft landing page", confidence=0.9, goal_ref=1, goal_link_confidence=0.8
        )
        created, mock_llm, _ = await self._created_task(mock_db, candidate, self.GOALS)
        assert created.goal_id == self.GOALS[0]["id"]
        assert created.goal_id_manually_set is False  # an AI link is never sticky
        mock_llm.assert_called_once_with("x", self.GOALS)

    @pytest.mark.asyncio
    async def test_unsure_link_is_not_saved(self, mock_db):
        candidate = ExtractedTaskCandidate(
            title="Draft landing page", confidence=0.9, goal_ref=1, goal_link_confidence=0.69
        )
        created, _, _ = await self._created_task(mock_db, candidate, self.GOALS)
        assert created.goal_id is None

    @pytest.mark.asyncio
    async def test_number_not_shown_is_ignored(self, mock_db):
        candidate = ExtractedTaskCandidate(
            title="Draft landing page", confidence=0.9, goal_ref=5, goal_link_confidence=0.95
        )
        created, _, _ = await self._created_task(mock_db, candidate, self.GOALS)
        assert created.goal_id is None

    @pytest.mark.asyncio
    async def test_no_open_goals_means_no_link(self, mock_db):
        candidate = ExtractedTaskCandidate(
            title="Draft landing page", confidence=0.9, goal_ref=1, goal_link_confidence=0.95
        )
        created, _, _ = await self._created_task(mock_db, candidate, [])
        assert created.goal_id is None

    @pytest.mark.asyncio
    async def test_record_jsonb_shows_the_accepted_link(self, mock_db):
        candidate = ExtractedTaskCandidate(
            title="Draft landing page", confidence=0.9, goal_ref=2, goal_link_confidence=0.9
        )
        _, _, mock_record_create = await self._created_task(mock_db, candidate, self.GOALS)
        stored = mock_record_create.call_args.kwargs["object"]
        assert stored.tasks[0].goal_id == self.GOALS[1]["id"]


class TestRecordJsonSerialization:
    """Known debt D-08: dates and UUIDs inside the JSONB lists must be JSON-safe after
    FastCRUD's Python-mode `model_dump()`."""

    def test_python_mode_dump_is_json_safe(self):
        candidate = ExtractedTaskCandidate(title="Send report", due_date=date(2026, 9, 30), confidence=0.9)
        candidate.goal_id = uuid4()
        record = MemoryExtractionRecordCreate(
            user_id=uuid4(),
            source_type="email",
            summary="s",
            tasks=[candidate],
            goals=[ExtractedGoal(title="g", target_date=date(2027, 1, 1), confidence=0.8)],
        )
        dumped = record.model_dump()
        assert json.loads(json.dumps(dumped["tasks"]))[0]["due_date"] == "2026-09-30"
        assert json.loads(json.dumps(dumped["goals"]))[0]["target_date"] == "2027-01-01"
        assert dumped["tasks"][0]["goal_id"] == str(candidate.goal_id)

    def test_goal_id_is_hidden_from_the_llm_schema(self):
        schema = json.dumps(MemoryExtractionResult.model_json_schema())
        assert "goal_ref" in schema and "goal_link_confidence" in schema
        assert '"goal_id"' not in schema
