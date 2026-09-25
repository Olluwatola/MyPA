"""Unit tests for core/goals/context.py — the one place "only OPEN goals feed reasoning"
lives (required proof (h)), the numbered prompt format, and the single rule for a
"confident" AI task -> goal link (required proof (f))."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uuid6 import uuid7

from src.app.core.goals import context

MODULE = "src.app.core.goals.context"

GOALS = [
    {"id": uuid7(), "title": "Launch ClientPal", "description": None, "horizon": "short_term"},
    {"id": uuid7(), "title": "Run a marathon", "description": None, "horizon": "long_term"},
    {"id": uuid7(), "title": "Read more", "description": None, "horizon": None},
]


class TestLoadOpenGoals:
    @pytest.mark.asyncio
    async def test_only_open_non_deleted_goals_newest_first_and_capped(self, mock_db):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [GOALS[0]]
        mock_db.execute = AsyncMock(return_value=result)
        user_id = uuid7()

        goals = await context.load_open_goals(mock_db, user_id)

        assert goals == [GOALS[0]]
        stmt = mock_db.execute.call_args.args[0]
        sql = str(stmt.compile())
        params = stmt.compile().params
        assert "goals.status = :status_1" in sql and params["status_1"] == "open"
        assert "goals.is_deleted IS false" in sql
        assert "goals.user_id = :user_id_1" in sql and params["user_id_1"] == user_id
        assert "ORDER BY goals.created_at DESC" in sql
        assert params["param_1"] == context.settings.GOAL_CONTEXT_MAX_OPEN_GOALS

    @pytest.mark.asyncio
    async def test_warns_when_cap_is_hit(self, mock_db):
        result = MagicMock()
        result.mappings.return_value.all.return_value = GOALS[:2]
        mock_db.execute = AsyncMock(return_value=result)
        with (
            patch(f"{MODULE}.settings") as mock_settings,
            patch(f"{MODULE}.logger") as mock_logger,
        ):
            mock_settings.GOAL_CONTEXT_MAX_OPEN_GOALS = 2
            await context.load_open_goals(mock_db, uuid7())
        mock_logger.warning.assert_called_once()


class TestFormatGoalsForPrompt:
    def test_numbered_with_readable_horizon(self):
        assert context.format_goals_for_prompt(GOALS) == (
            "[1] Launch ClientPal (short term)\n[2] Run a marathon (long term)\n[3] Read more"
        )

    def test_empty_list_is_empty_string(self):
        assert context.format_goals_for_prompt([]) == ""

    def test_chat_format_is_bullets_without_numbers(self):
        assert context.format_goals_for_chat(GOALS[:1]) == "- Launch ClientPal (short term)"


class TestResolveGoalLink:
    def test_confident_pick_from_the_list_is_accepted(self):
        assert context.resolve_goal_link(2, 0.7, GOALS) == GOALS[1]["id"]

    def test_below_threshold_is_rejected(self):
        assert context.resolve_goal_link(2, 0.69, GOALS) is None

    @pytest.mark.parametrize("goal_ref", [0, -1, 4, 99])
    def test_number_not_shown_is_rejected(self, goal_ref):
        assert context.resolve_goal_link(goal_ref, 0.99, GOALS) is None

    def test_missing_ref_or_confidence_is_rejected(self):
        assert context.resolve_goal_link(None, 0.99, GOALS) is None
        assert context.resolve_goal_link(1, None, GOALS) is None

    def test_no_goals_shown_means_no_link(self):
        assert context.resolve_goal_link(1, 0.99, []) is None
