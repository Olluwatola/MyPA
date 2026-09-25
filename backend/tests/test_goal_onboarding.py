"""Unit tests for core/goals/onboarding.py — required proof (e): onboarding never suggests,
and never creates, a goal the user already has."""

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.goals import onboarding
from src.app.core.items import dedup
from src.app.schemas.goal import SuggestedGoal

MODULE = "src.app.core.goals.onboarding"
BASE = [1.0, 0.0]


def _vector(similarity_to_base: float) -> list[float]:
    return [similarity_to_base, math.sqrt(1 - similarity_to_base**2)]


def _pool_goal(**overrides) -> dict:
    return {
        "id": uuid7(),
        "title": "Close the seed round",
        "description": None,
        "horizon": None,
        "target_date": None,
        "status": "open",
        "is_deleted": False,
        "description_manually_set": False,
    } | overrides


def _patches(pool, embeddings):
    return (
        patch(f"{MODULE}.load_dedup_pool", new=AsyncMock(return_value=pool)),
        patch(f"{MODULE}.embed_texts", new=AsyncMock(return_value=embeddings)),
    )


class TestDropExistingGoalSuggestions:
    @pytest.mark.asyncio
    async def test_suggestion_matching_an_existing_goal_is_dropped(self, mock_db):
        dup, fresh = SuggestedGoal(title="Raise the seed round"), SuggestedGoal(title="Hire a designer")
        pool_patch, embed_patch = _patches([_pool_goal()], [BASE, _vector(0.1), _vector(0.9)])
        with pool_patch, embed_patch as mock_embed:
            kept = await onboarding.drop_existing_goal_suggestions(mock_db, uuid7(), [dup, fresh])

        assert kept == [fresh]
        mock_embed.assert_awaited_once_with(["Raise the seed round", "Hire a designer", "Close the seed round"])

    @pytest.mark.asyncio
    async def test_matches_any_pooled_status_including_paused(self, mock_db):
        pool_patch, embed_patch = _patches([_pool_goal(status="paused")], [BASE, BASE])
        with pool_patch, embed_patch:
            kept = await onboarding.drop_existing_goal_suggestions(mock_db, uuid7(), [SuggestedGoal(title="x")])
        assert kept == []

    @pytest.mark.asyncio
    async def test_no_existing_goals_keeps_everything_without_embedding(self, mock_db):
        suggestions = [SuggestedGoal(title="Hire a designer")]
        pool_patch, embed_patch = _patches([], [])
        with pool_patch, embed_patch as mock_embed:
            assert await onboarding.drop_existing_goal_suggestions(mock_db, uuid7(), suggestions) == suggestions
        mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_the_goal_pool(self, mock_db):
        with patch(f"{MODULE}.load_dedup_pool", new=AsyncMock(return_value=[])) as mock_pool:
            await onboarding.drop_existing_goal_suggestions(mock_db, uuid7(), [SuggestedGoal(title="x")])
        assert mock_pool.call_args.args[1].label == "goal"


class TestResolveCheckedSuggestions:
    @pytest.mark.asyncio
    async def test_open_match_fills_blanks_and_is_not_created(self, mock_db):
        existing = _pool_goal()
        suggestion = SuggestedGoal(title="Raise the seed round", description="$1.5M", horizon="short_term")
        mock_crud = MagicMock(update=AsyncMock())
        pool_patch, embed_patch = _patches([existing], [BASE, _vector(0.9)])
        with pool_patch, embed_patch, patch.object(dedup, "crud_goals", mock_crud):
            to_create = await onboarding.resolve_checked_suggestions(mock_db, uuid7(), [suggestion])

        assert to_create == []
        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["object"] == {"description": "$1.5M", "horizon": "short_term"}
        assert kwargs["commit"] is False

    @pytest.mark.asyncio
    async def test_paused_match_is_skipped_without_fill(self, mock_db):
        mock_crud = MagicMock(update=AsyncMock())
        pool_patch, embed_patch = _patches([_pool_goal(status="paused")], [BASE, _vector(0.9)])
        with pool_patch, embed_patch, patch.object(dedup, "crud_goals", mock_crud):
            to_create = await onboarding.resolve_checked_suggestions(
                mock_db, uuid7(), [SuggestedGoal(title="x", description="new")]
            )
        assert to_create == []
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_match_is_created(self, mock_db):
        suggestion = SuggestedGoal(title="Hire a designer")
        pool_patch, embed_patch = _patches([_pool_goal()], [BASE, _vector(0.2)])
        with pool_patch, embed_patch:
            assert await onboarding.resolve_checked_suggestions(mock_db, uuid7(), [suggestion]) == [suggestion]

    @pytest.mark.asyncio
    async def test_nothing_checked_does_nothing(self, mock_db):
        with patch(f"{MODULE}.load_dedup_pool", new=AsyncMock()) as mock_pool:
            assert await onboarding.resolve_checked_suggestions(mock_db, uuid7(), []) == []
        mock_pool.assert_not_called()
