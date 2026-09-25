"""Unit tests for the manual-create background horizon guess: the `medium`-tier LLM call
(core/llm/goal_horizon_guess.py) and the ARQ job (core/goals/jobs.py) — it only fills a
horizon that is still empty, never one the user set meanwhile, and leaves it empty on
failure."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from arq import Retry
from sqlalchemy.exc import NoResultFound
from uuid6 import uuid7

from src.app.core.goals.jobs import GOAL_HORIZON_GUESS_MAX_TRIES, guess_goal_horizon
from src.app.core.llm import service as llm_service_module
from src.app.core.llm.goal_horizon_guess import call_goal_horizon_guess_llm
from src.app.core.llm.provider import LlmCompletionResult, LlmUsage
from src.app.core.llm.service import LlmService
from src.app.core.worker import WorkerSettings
from src.app.schemas.goal import GoalHorizonGuess

JOB_MODULE = "src.app.core.goals.jobs"


def _goal(**overrides) -> dict:
    return {
        "id": uuid7(),
        "title": "Run a marathon",
        "description": None,
        "target_date": date(2027, 4, 1),
        "horizon": None,
    } | overrides


class TestCallGoalHorizonGuessLlm:
    @pytest.mark.asyncio
    async def test_uses_medium_tier_and_sends_the_goal(self):
        fake_service = AsyncMock(spec=LlmService)
        fake_service.complete = AsyncMock(
            return_value=LlmCompletionResult(
                text='{"horizon": "long_term"}',
                model="fake",
                provider="fake",
                usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
            )
        )
        with patch.object(llm_service_module, "llm_service", fake_service):
            result = await call_goal_horizon_guess_llm("Run a marathon", "Sub-4 hours", date(2027, 4, 1))

        assert result == GoalHorizonGuess(horizon="long_term")
        kwargs = fake_service.complete.call_args.kwargs
        assert kwargs["tier"] == "medium"
        user_message = kwargs["messages"][-1].content
        assert "Title: Run a marathon" in user_message
        assert "Description: Sub-4 hours" in user_message
        assert "Target date: 2027-04-01" in user_message


class TestGuessGoalHorizon:
    async def _run(self, goal, guess=None, update_side_effect=None):
        with (
            patch(f"{JOB_MODULE}.local_session") as mock_session_factory,
            patch(f"{JOB_MODULE}.crud_goals") as mock_crud,
            patch(f"{JOB_MODULE}.call_goal_horizon_guess_llm", new=AsyncMock(return_value=guess)) as mock_llm,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_crud.get = AsyncMock(return_value=goal)
            mock_crud.update = AsyncMock(side_effect=update_side_effect)
            await guess_goal_horizon({"job_try": 1}, str(uuid7()))
        return mock_crud, mock_llm

    @pytest.mark.asyncio
    async def test_fills_empty_horizon_with_a_conditional_write(self):
        goal = _goal()
        mock_crud, _ = await self._run(goal, GoalHorizonGuess(horizon="long_term"))

        assert mock_crud.get.call_args.kwargs["is_deleted"] is False
        kwargs = mock_crud.update.call_args.kwargs
        assert kwargs["object"] == {"horizon": "long_term"}
        assert kwargs["id"] == goal["id"]
        # the "still empty" check is in the WHERE clause, so a value set meanwhile can't be overwritten
        assert kwargs["horizon"] is None and kwargs["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_horizon_already_set_means_no_llm_call(self):
        mock_crud, mock_llm = await self._run(_goal(horizon="short_term"))
        mock_llm.assert_not_called()
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_set_it_while_llm_was_thinking(self):
        mock_crud, _ = await self._run(_goal(), GoalHorizonGuess(horizon="long_term"), NoResultFound())
        mock_crud.update.assert_called_once()  # tried, found nothing to update, no error

    @pytest.mark.asyncio
    async def test_unsure_guess_writes_nothing(self):
        mock_crud, _ = await self._run(_goal(), GoalHorizonGuess(horizon=None))
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_deleted_goal_is_a_noop(self):
        mock_crud, mock_llm = await self._run(None)
        mock_llm.assert_not_called()
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_retries_and_writes_nothing(self):
        with (
            patch(f"{JOB_MODULE}.local_session") as mock_session_factory,
            patch(f"{JOB_MODULE}.crud_goals") as mock_crud,
            patch(f"{JOB_MODULE}.call_goal_horizon_guess_llm", new=AsyncMock(side_effect=RuntimeError("down"))),
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_crud.get = AsyncMock(return_value=_goal())
            mock_crud.update = AsyncMock()
            with pytest.raises(Retry):
                await guess_goal_horizon({"job_try": 1}, str(uuid7()))
        mock_crud.update.assert_not_called()


class TestWorkerRegistration:
    def test_guess_job_registered_with_bounded_retries(self):
        registered = {job.name: job for job in WorkerSettings.functions}  # type: ignore[attr-defined]
        assert registered["guess_goal_horizon"].max_tries == GOAL_HORIZON_GUESS_MAX_TRIES == 3
