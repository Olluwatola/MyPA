"""Unit tests for Notion "insufficient context" goal resolution
(core/notion/goal_resolution.py). Required proof (g): a MANUAL goal (no memory record) is
now matched — the 1.7 gap — while the absolute-threshold + margin-over-runner-up safety
check is kept. Embeddings are faked with 2-d unit vectors so scores are exact."""

import math
from unittest.mock import AsyncMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.notion.goal_resolution import resolve_against_existing_goals

MODULE = "src.app.core.notion.goal_resolution"
BASE = [1.0, 0.0]


def _vector(similarity_to_base: float) -> list[float]:
    return [similarity_to_base, math.sqrt(1 - similarity_to_base**2)]


def _goal(title: str) -> dict:
    # A manual goal: nothing ties it to a memory record or a stored embedding.
    return {"id": uuid7(), "title": title, "description": None, "horizon": None}


async def _resolve(mock_db, goals, goal_vectors):
    with (
        patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=goals)),
        patch(f"{MODULE}.embed_texts", new=AsyncMock(return_value=[BASE, *goal_vectors])) as mock_embed,
    ):
        result = await resolve_against_existing_goals(mock_db, uuid7(), "update the prd and system design")
    return result, mock_embed


class TestResolveAgainstExistingGoals:
    @pytest.mark.asyncio
    async def test_manual_goal_is_matched(self, mock_db):
        manual = _goal("Launch ClientPal")
        result, mock_embed = await _resolve(mock_db, [manual], [_vector(0.9)])
        assert result == manual["id"]
        # one batch: the block summary plus every goal's "title. description"
        mock_embed.assert_awaited_once_with(["update the prd and system design", "Launch ClientPal. "])

    @pytest.mark.asyncio
    async def test_best_below_threshold_returns_none(self, mock_db):
        result, _ = await _resolve(mock_db, [_goal("Launch ClientPal")], [_vector(0.79)])
        assert result is None

    @pytest.mark.asyncio
    async def test_two_close_goals_is_ambiguous(self, mock_db):
        result, _ = await _resolve(
            mock_db, [_goal("Launch ClientPal"), _goal("ClientPal v2")], [_vector(0.9), _vector(0.87)]
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_clear_winner_over_runner_up_is_returned(self, mock_db):
        winner, other = _goal("Launch ClientPal"), _goal("Run a marathon")
        result, _ = await _resolve(mock_db, [other, winner], [_vector(0.3), _vector(0.9)])
        assert result == winner["id"]

    @pytest.mark.asyncio
    async def test_no_open_goals_returns_none_without_embedding(self, mock_db):
        with (
            patch(f"{MODULE}.load_open_goals", new=AsyncMock(return_value=[])),
            patch(f"{MODULE}.embed_texts", new=AsyncMock()) as mock_embed,
        ):
            assert await resolve_against_existing_goals(mock_db, uuid7(), "x") is None
        mock_embed.assert_not_called()

    def test_no_longer_goes_through_memory_records(self):
        """The old path (search_similar_memories -> goal by memory_record_id) is gone."""
        import src.app.core.notion.goal_resolution as module

        assert not hasattr(module, "search_similar_memories")
        assert not hasattr(module, "crud_embeddings")
