"""Unit tests for near-duplicate task handling (core/tasks/dedup.py). Embeddings are
faked with small hand-made vectors so similarity scores are known exactly;
`cosine_similarity` itself stays real."""

import math
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.tasks import dedup
from src.app.schemas.memory_extraction_record import ExtractedTaskCandidate

MODULE = "src.app.core.tasks.dedup"


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
        "status": "open",
        "is_deleted": False,
        "description_manually_set": False,
        "effort_level_manually_set": False,
    } | overrides


def _candidate(**overrides) -> ExtractedTaskCandidate:
    return ExtractedTaskCandidate(**({"title": "Send the signed contract to John", "confidence": 0.9} | overrides))


class TestLoadDedupPool:
    @pytest.mark.asyncio
    async def test_query_covers_open_recent_done_and_recent_deleted(self, mock_db):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{"id": 1, "title": "x"}]
        mock_db.execute = AsyncMock(return_value=result)
        user_id = uuid7()

        pool = await dedup.load_dedup_pool(mock_db, user_id)

        assert pool == [{"id": 1, "title": "x"}]
        stmt = mock_db.execute.call_args.args[0]
        sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "tasks.user_id = :user_id_1" in sql
        assert "tasks.status = :status_1" in sql and "tasks.status = :status_2" in sql
        assert "tasks.updated_at >= :updated_at_1" in sql
        assert "tasks.deleted_at >= :deleted_at_1" in sql
        assert "ORDER BY tasks.created_at DESC" in sql
        params = stmt.compile().params
        assert params["status_1"] == "open" and params["status_2"] == "done"
        assert params["param_1"] == dedup.settings.TASK_DEDUP_MAX_EXISTING_TASKS

    @pytest.mark.asyncio
    async def test_cutoff_uses_lookback_setting(self, mock_db):
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        with patch(f"{MODULE}.settings") as mock_settings:
            mock_settings.TASK_DEDUP_LOOKBACK_DAYS = 60
            mock_settings.TASK_DEDUP_MAX_EXISTING_TASKS = 500
            await dedup.load_dedup_pool(mock_db, uuid7())

        params = mock_db.execute.call_args.args[0].compile().params
        cutoff = params["updated_at_1"]
        assert params["deleted_at_1"] == cutoff
        assert abs((datetime.now(UTC) - timedelta(days=60)) - cutoff) < timedelta(seconds=5)


class TestFindBestMatch:
    def test_exactly_threshold_matches(self):
        task = _pool_task()
        assert dedup.find_best_match(BASE, [task], [_vector(0.85)]) == (task, pytest.approx(0.85))

    def test_just_below_threshold_does_not_match(self):
        assert dedup.find_best_match(BASE, [_pool_task()], [_vector(0.849)]) is None

    def test_highest_score_wins(self):
        low, high = _pool_task(), _pool_task()
        match = dedup.find_best_match(BASE, [low, high], [_vector(0.86), _vector(0.95)])
        assert match is not None and match[0] is high


class TestMergeCandidateDuplicates:
    def test_duplicates_collapse_into_highest_confidence_with_blanks_merged(self):
        strong = _candidate(confidence=0.95)
        weak = _candidate(confidence=0.75, due_date=date(2026, 10, 2), description="By Friday")
        kept = dedup.merge_candidate_duplicates([weak, strong], [BASE, _vector(0.9)])

        assert len(kept) == 1
        merged, _ = kept[0]
        assert merged.confidence == 0.95
        assert merged.due_date == date(2026, 10, 2)
        assert merged.description == "By Friday"

    def test_different_candidates_both_kept(self):
        kept = dedup.merge_candidate_duplicates([_candidate(), _candidate(title="Call mum")], [BASE, _vector(0.2)])
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
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.update = AsyncMock()
            await dedup.fill_blanks(mock_db, existing, candidate)

        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["object"] == {"description": "Scanned copy", "effort_level": "light_focus"}
        assert kwargs["commit"] is False
        assert kwargs["id"] == existing["id"]
        assert existing["description"] == "Scanned copy"  # updated in place

    @pytest.mark.asyncio
    async def test_nothing_to_fill_means_no_write(self, mock_db):
        existing = _pool_task(due_date=date(2026, 9, 30), description="x", effort_level="passive")
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.update = AsyncMock()
            await dedup.fill_blanks(
                mock_db, existing, _candidate(due_date=date(2026, 10, 1), description="y", effort_level="deep_focus")
            )
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_sticky_empty_fields_are_not_filled(self, mock_db):
        existing = _pool_task(description_manually_set=True, effort_level_manually_set=True)
        with patch(f"{MODULE}.crud_tasks") as mock_crud:
            mock_crud.update = AsyncMock()
            await dedup.fill_blanks(mock_db, existing, _candidate(description="y", effort_level="deep_focus"))
        mock_crud.update.assert_not_called()


class TestResolveCandidates:
    async def _resolve(self, mock_db, pool, candidates, embeddings):
        with (
            patch(f"{MODULE}.load_dedup_pool", new=AsyncMock(return_value=pool)),
            patch(f"{MODULE}.embed_texts", new=AsyncMock(return_value=embeddings)) as mock_embed,
            patch(f"{MODULE}.crud_tasks") as mock_crud,
        ):
            mock_crud.update = AsyncMock()
            to_create = await dedup.resolve_candidates(mock_db, uuid7(), candidates)
        return to_create, mock_crud, mock_embed

    @pytest.mark.asyncio
    async def test_no_candidates_skips_everything(self, mock_db):
        with (
            patch(f"{MODULE}.load_dedup_pool", new=AsyncMock()) as mock_pool,
            patch(f"{MODULE}.embed_texts", new=AsyncMock()) as mock_embed,
        ):
            assert await dedup.resolve_candidates(mock_db, uuid7(), []) == []
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
