"""Unit tests for near-duplicate handling of tasks and goals (core/items/dedup.py).
Embeddings are faked with small hand-made vectors so similarity scores are known exactly;
`cosine_similarity` itself stays real. The task cases are 1.8's, unchanged in meaning —
they prove the shared engine behaves exactly as the old task-only module did."""

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.items import dedup
from src.app.schemas.memory_extraction_record import ExtractedGoal, ExtractedTaskCandidate

MODULE = "src.app.core.items.dedup"


def _vector(similarity_to_base: float) -> list[float]:
    """A 2-d unit vector whose cosine similarity to BASE ([1, 0]) is exactly the argument."""
    return [similarity_to_base, math.sqrt(1 - similarity_to_base**2)]


BASE = [1.0, 0.0]


def _pool_task(**overrides) -> dict:
    return {
        "id": uuid7(),
        "title": "Send John the signed contract",
        "description": None,
        "due_date": None,
        "effort_level": None,
        "goal_id": None,
        "status": "open",
        "is_deleted": False,
        "description_manually_set": False,
        "effort_level_manually_set": False,
        "goal_id_manually_set": False,
    } | overrides


def _pool_goal(**overrides) -> dict:
    return {
        "id": uuid7(),
        "title": "Launch ClientPal",
        "description": None,
        "horizon": None,
        "target_date": None,
        "status": "open",
        "is_deleted": False,
        "description_manually_set": False,
    } | overrides


def _candidate(**overrides) -> ExtractedTaskCandidate:
    return ExtractedTaskCandidate(**({"title": "Send the signed contract to John", "confidence": 0.9} | overrides))


def _goal(**overrides) -> ExtractedGoal:
    return ExtractedGoal(**({"title": "Ship ClientPal", "confidence": 0.9} | overrides))


def _sql_and_params(mock_db) -> tuple[str, dict]:
    stmt = mock_db.execute.call_args.args[0]
    return str(stmt.compile()), stmt.compile().params


def _empty_result() -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    return result


class TestLoadDedupPool:
    @pytest.mark.asyncio
    async def test_task_query_covers_open_recent_done_and_recent_deleted(self, mock_db):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{"id": 1, "title": "x"}]
        mock_db.execute = AsyncMock(return_value=result)

        pool = await dedup.load_dedup_pool(mock_db, dedup.task_dedup_spec(), uuid7())

        assert pool == [{"id": 1, "title": "x"}]
        sql, params = _sql_and_params(mock_db)
        assert "tasks.user_id = :user_id_1" in sql
        assert "tasks.updated_at >= :updated_at_1" in sql
        assert "tasks.deleted_at >= :deleted_at_1" in sql
        assert "ORDER BY tasks.created_at DESC" in sql
        assert "tasks.goal_id" in sql and "tasks.goal_id_manually_set" in sql
        assert params["status_1"] == ["open"] and params["status_2"] == ["done"]
        assert params["param_1"] == dedup.settings.TASK_DEDUP_MAX_EXISTING_TASKS

    @pytest.mark.asyncio
    async def test_goal_query_keeps_paused_always_and_dropped_for_the_window(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_empty_result())

        await dedup.load_dedup_pool(mock_db, dedup.goal_dedup_spec(), uuid7())

        sql, params = _sql_and_params(mock_db)
        assert "goals.user_id = :user_id_1" in sql
        assert "goals.updated_at >= :updated_at_1" in sql
        assert "goals.deleted_at >= :deleted_at_1" in sql
        assert params["status_1"] == ["open", "paused"]
        assert params["status_2"] == ["done", "dropped"]
        assert params["param_1"] == 200

    @pytest.mark.asyncio
    async def test_cutoff_uses_lookback_setting(self, mock_db):
        mock_db.execute = AsyncMock(return_value=_empty_result())

        with patch(f"{MODULE}.settings") as mock_settings:
            mock_settings.TASK_DEDUP_LOOKBACK_DAYS = 60
            mock_settings.TASK_DEDUP_MAX_EXISTING_TASKS = 500
            await dedup.load_dedup_pool(mock_db, dedup.task_dedup_spec(), uuid7())

        _, params = _sql_and_params(mock_db)
        cutoff = params["updated_at_1"]
        assert params["deleted_at_1"] == cutoff
        assert abs((datetime.now(UTC) - timedelta(days=60)) - cutoff) < timedelta(seconds=5)


class TestFindBestMatch:
    def test_exactly_threshold_matches(self):
        task = _pool_task()
        assert dedup.find_best_match(BASE, [task], [_vector(0.85)], 0.85) == (task, pytest.approx(0.85))

    def test_just_below_threshold_does_not_match(self):
        assert dedup.find_best_match(BASE, [_pool_task()], [_vector(0.849)], 0.85) is None

    def test_highest_score_wins(self):
        low, high = _pool_task(), _pool_task()
        match = dedup.find_best_match(BASE, [low, high], [_vector(0.86), _vector(0.95)], 0.85)
        assert match is not None and match[0] is high


class TestMergeCandidateDuplicates:
    def test_duplicates_collapse_into_highest_confidence_with_blanks_merged(self):
        strong = _candidate(confidence=0.95)
        weak = _candidate(confidence=0.75, due_date=date(2026, 10, 2), description="By Friday")
        kept = dedup.merge_candidate_duplicates(dedup.task_dedup_spec(), [weak, strong], [BASE, _vector(0.9)])

        assert len(kept) == 1
        merged, _ = kept[0]
        assert merged.confidence == 0.95
        assert merged.due_date == date(2026, 10, 2)
        assert merged.description == "By Friday"

    def test_different_candidates_both_kept(self):
        kept = dedup.merge_candidate_duplicates(
            dedup.task_dedup_spec(), [_candidate(), _candidate(title="Call mum")], [BASE, _vector(0.2)]
        )
        assert len(kept) == 2


class TestFillBlanks:
    @pytest.mark.asyncio
    async def test_fills_only_empty_eligible_fields(self, mock_db):
        existing = _pool_task(due_date=date(2026, 9, 30))
        candidate = _candidate(
            title="A different title",
            urgency="high",
            due_date=date(2026, 10, 9),
            description="Scanned copy",
            effort_level="light_focus",
        )
        mock_crud = MagicMock(update=AsyncMock())
        with patch.object(dedup, "crud_tasks", mock_crud):
            await dedup.fill_blanks(mock_db, dedup.task_dedup_spec(), existing, candidate.model_dump())

        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["object"] == {"description": "Scanned copy", "effort_level": "light_focus"}
        assert kwargs["commit"] is False
        assert kwargs["id"] == existing["id"]
        assert existing["description"] == "Scanned copy"  # updated in place

    @pytest.mark.asyncio
    async def test_nothing_to_fill_means_no_write(self, mock_db):
        existing = _pool_task(due_date=date(2026, 9, 30), description="x", effort_level="passive")
        mock_crud = MagicMock(update=AsyncMock())
        with patch.object(dedup, "crud_tasks", mock_crud):
            candidate = _candidate(due_date=date(2026, 10, 1), description="y", effort_level="deep_focus")
            await dedup.fill_blanks(mock_db, dedup.task_dedup_spec(), existing, candidate.model_dump())
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_sticky_empty_fields_are_not_filled(self, mock_db):
        existing = _pool_task(description_manually_set=True, effort_level_manually_set=True)
        mock_crud = MagicMock(update=AsyncMock())
        with patch.object(dedup, "crud_tasks", mock_crud):
            candidate = _candidate(description="y", effort_level="deep_focus")
            await dedup.fill_blanks(mock_db, dedup.task_dedup_spec(), existing, candidate.model_dump())
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_unlinked_open_task_gets_confident_goal_link(self, mock_db):
        goal_id = uuid.uuid4()
        mock_crud = MagicMock(update=AsyncMock())
        with patch.object(dedup, "crud_tasks", mock_crud):
            await dedup.fill_blanks(mock_db, dedup.task_dedup_spec(), _pool_task(), {"goal_id": goal_id})
        assert mock_crud.update.call_args.kwargs["object"] == {"goal_id": goal_id}

    @pytest.mark.asyncio
    async def test_user_set_or_cleared_goal_link_is_never_filled(self, mock_db):
        existing = _pool_task(goal_id_manually_set=True)
        mock_crud = MagicMock(update=AsyncMock())
        with patch.object(dedup, "crud_tasks", mock_crud):
            await dedup.fill_blanks(mock_db, dedup.task_dedup_spec(), existing, {"goal_id": uuid.uuid4()})
        mock_crud.update.assert_not_called()


class TestResolveCandidates:
    async def _resolve(self, mock_db, pool, candidates, embeddings, spec_fn=dedup.task_dedup_spec):
        mock_crud = MagicMock(update=AsyncMock())
        crud_name = "crud_tasks" if spec_fn is dedup.task_dedup_spec else "crud_goals"
        with (
            patch(f"{MODULE}.load_dedup_pool", new=AsyncMock(return_value=pool)),
            patch(f"{MODULE}.embed_texts", new=AsyncMock(return_value=embeddings)) as mock_embed,
            patch.object(dedup, crud_name, mock_crud),
        ):
            to_create = await dedup.resolve_candidates(mock_db, spec_fn(), uuid7(), candidates)
        return to_create, mock_crud, mock_embed

    @pytest.mark.asyncio
    async def test_no_candidates_skips_everything(self, mock_db):
        with (
            patch(f"{MODULE}.load_dedup_pool", new=AsyncMock()) as mock_pool,
            patch(f"{MODULE}.embed_texts", new=AsyncMock()) as mock_embed,
        ):
            assert await dedup.resolve_candidates(mock_db, dedup.task_dedup_spec(), uuid7(), []) == []
        mock_pool.assert_not_called()
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_embeds_candidate_and_pool_titles_in_one_batch(self, mock_db):
        pool = [_pool_task(title="Pay rent")]
        _, _, mock_embed = await self._resolve(mock_db, pool, [_candidate()], [BASE, _vector(0.1)])
        mock_embed.assert_called_once_with(["Send the signed contract to John", "Pay rent"])

    @pytest.mark.asyncio
    async def test_match_on_open_task_fills_blanks_instead_of_creating(self, mock_db):
        existing = _pool_task()
        candidate = _candidate(due_date=date(2026, 10, 2))
        to_create, mock_crud, _ = await self._resolve(mock_db, [existing], [candidate], [BASE, _vector(0.9)])

        assert to_create == []
        assert mock_crud.update.call_args.kwargs["object"] == {"due_date": date(2026, 10, 2)}

    @pytest.mark.asyncio
    async def test_match_on_done_task_inside_window_skips(self, mock_db):
        existing = _pool_task(status="done")
        to_create, mock_crud, _ = await self._resolve(
            mock_db, [existing], [_candidate(due_date=date(2026, 10, 2))], [BASE, _vector(0.9)]
        )
        assert to_create == []
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_match_on_deleted_task_inside_window_skips(self, mock_db):
        existing = _pool_task(is_deleted=True)
        to_create, mock_crud, _ = await self._resolve(
            mock_db, [existing], [_candidate(description="x")], [BASE, _vector(0.95)]
        )
        assert to_create == []
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_done_or_deleted_outside_window_is_not_in_pool_so_candidate_is_created(self, mock_db):
        candidate = _candidate()
        to_create, _, _ = await self._resolve(mock_db, [], [candidate], [BASE])
        assert to_create == [candidate]

    @pytest.mark.asyncio
    async def test_below_threshold_is_created(self, mock_db):
        candidate = _candidate()
        to_create, mock_crud, _ = await self._resolve(mock_db, [_pool_task()], [candidate], [BASE, _vector(0.84)])
        assert to_create == [candidate]
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_two_near_identical_candidates_create_one_task(self, mock_db):
        first = _candidate(confidence=0.95)
        second = _candidate(confidence=0.8, due_date=date(2026, 10, 2))
        to_create, _, _ = await self._resolve(mock_db, [], [first, second], [BASE, _vector(0.97)])

        assert len(to_create) == 1
        assert to_create[0].confidence == 0.95
        assert to_create[0].due_date == date(2026, 10, 2)


class TestResolveGoalCandidates:
    """Goal dedup = the task rules (decisions-log.md 2026-09-24): skip on a match, fill
    blanks only on an OPEN match, 60-day window for done/dropped/deleted."""

    async def _resolve(self, mock_db, pool, candidates, embeddings):
        return await TestResolveCandidates._resolve(
            TestResolveCandidates(), mock_db, pool, candidates, embeddings, spec_fn=dedup.goal_dedup_spec
        )

    @pytest.mark.asyncio
    async def test_open_match_fills_only_empty_goal_fields(self, mock_db):
        existing = _pool_goal(horizon="long_term")
        candidate = _goal(description="Public launch", horizon="short_term", target_date=date(2027, 3, 1))
        to_create, mock_crud, _ = await self._resolve(mock_db, [existing], [candidate], [BASE, _vector(0.9)])

        assert to_create == []
        assert mock_crud.update.call_args.kwargs["object"] == {
            "description": "Public launch",
            "target_date": date(2027, 3, 1),
        }

    @pytest.mark.asyncio
    async def test_sticky_description_is_not_filled(self, mock_db):
        existing = _pool_goal(description_manually_set=True)
        to_create, mock_crud, _ = await self._resolve(
            mock_db, [existing], [_goal(description="x")], [BASE, _vector(0.9)]
        )
        assert to_create == []
        mock_crud.update.assert_not_called()

    @pytest.mark.parametrize(
        "existing", [_pool_goal(status="paused"), _pool_goal(status="done"), _pool_goal(status="dropped")]
    )
    @pytest.mark.asyncio
    async def test_paused_done_or_dropped_match_is_skipped_without_fill(self, mock_db, existing):
        to_create, mock_crud, _ = await self._resolve(
            mock_db, [existing], [_goal(description="new detail")], [BASE, _vector(0.9)]
        )
        assert to_create == []
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_deleted_goal_inside_window_is_skipped(self, mock_db):
        to_create, mock_crud, _ = await self._resolve(
            mock_db, [_pool_goal(is_deleted=True)], [_goal()], [BASE, _vector(0.95)]
        )
        assert to_create == []
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_outside_window_not_in_pool_so_created(self, mock_db):
        candidate = _goal()
        to_create, _, _ = await self._resolve(mock_db, [], [candidate], [BASE])
        assert to_create == [candidate]

    @pytest.mark.asyncio
    async def test_below_threshold_is_created(self, mock_db):
        candidate = _goal()
        to_create, _, _ = await self._resolve(mock_db, [_pool_goal()], [candidate], [BASE, _vector(0.84)])
        assert to_create == [candidate]
