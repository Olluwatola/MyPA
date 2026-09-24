"""Unit tests for the manual-create background AI guess: the `medium`-tier LLM call
(core/llm/task_field_guess.py) and the ARQ job (core/tasks/jobs.py) — it only fills
requested fields that are still empty and non-sticky, and leaves the defaults on failure."""

from unittest.mock import AsyncMock, patch

import pytest
from arq import Retry
from sqlalchemy.exc import NoResultFound
from uuid6 import uuid7

from src.app.core.llm import service as llm_service_module
from src.app.core.llm.provider import LlmCompletionResult, LlmUsage
from src.app.core.llm.service import LlmService
from src.app.core.llm.task_field_guess import call_task_field_guess_llm
from src.app.core.tasks.jobs import TASK_FIELD_GUESS_MAX_TRIES, guess_task_fields
from src.app.core.worker import WorkerSettings
from src.app.schemas.task import TaskFieldGuess

JOB_MODULE = "src.app.core.tasks.jobs"


def _task(**overrides) -> dict:
    return {
        "id": uuid7(),
        "title": "Prepare board deck",
        "description": None,
        "due_date": None,
        "urgency_manually_set": False,
        "effort_level_manually_set": False,
    } | overrides


class TestCallTaskFieldGuessLlm:
    @pytest.mark.asyncio
    async def test_uses_medium_tier_and_asks_only_for_requested_fields(self):
        fake_service = AsyncMock(spec=LlmService)
        fake_service.complete = AsyncMock(
            return_value=LlmCompletionResult(
                text='{"effort_level": "deep_focus"}',
                model="fake",
                provider="fake",
                usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
            )
        )
        with patch.object(llm_service_module, "llm_service", fake_service):
            result = await call_task_field_guess_llm("Prepare board deck", None, None, ["effort_level"])

        assert result == TaskFieldGuess(effort_level="deep_focus")
        kwargs = fake_service.complete.call_args.kwargs
        assert kwargs["tier"] == "medium"
        user_message = kwargs["messages"][-1].content
        assert "Fields to fill: effort_level" in user_message
        assert "urgency" not in user_message


class TestGuessTaskFields:
    async def _run(self, task, guess=None, update_side_effect=None, fields=None):
        with (
            patch(f"{JOB_MODULE}.local_session") as mock_session_factory,
            patch(f"{JOB_MODULE}.crud_tasks") as mock_crud,
            patch(f"{JOB_MODULE}.call_task_field_guess_llm", new=AsyncMock(return_value=guess)) as mock_llm,
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_crud.get = AsyncMock(return_value=task)
            mock_crud.update = AsyncMock(side_effect=update_side_effect)
            await guess_task_fields({"job_try": 1}, str(uuid7()), fields or ["urgency", "effort_level"])
        return mock_crud, mock_llm

    @pytest.mark.asyncio
    async def test_fills_requested_fields_with_flag_checked_at_write_time(self):
        task = _task()
        mock_crud, _ = await self._run(task, guess=TaskFieldGuess(urgency="high", effort_level="passive"))

        assert mock_crud.get.call_args.kwargs["is_deleted"] is False
        calls = [call.kwargs for call in mock_crud.update.call_args_list]
        assert calls[0]["object"] == {"urgency": "high"}
        assert calls[0]["urgency_manually_set"] is False and calls[0]["is_deleted"] is False
        assert calls[1]["object"] == {"effort_level": "passive"}
        assert calls[1]["effort_level_manually_set"] is False and calls[1]["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_field_flagged_since_create_is_not_requested(self):
        _, mock_llm = await self._run(_task(urgency_manually_set=True), guess=TaskFieldGuess(effort_level="passive"))
        assert mock_llm.call_args.args[3] == ["effort_level"]

    @pytest.mark.asyncio
    async def test_all_fields_flagged_means_no_llm_call(self):
        mock_crud, mock_llm = await self._run(_task(urgency_manually_set=True, effort_level_manually_set=True))
        mock_llm.assert_not_called()
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_edit_during_llm_call_is_not_overwritten(self):
        mock_crud, _ = await self._run(
            _task(),
            guess=TaskFieldGuess(urgency="high", effort_level="passive"),
            update_side_effect=[NoResultFound(), None],  # urgency got flagged mid-call
        )
        assert mock_crud.update.call_count == 2  # the effort_level write still happens

    @pytest.mark.asyncio
    async def test_unrequested_field_from_llm_is_ignored(self):
        mock_crud, _ = await self._run(
            _task(), guess=TaskFieldGuess(urgency="high", effort_level="passive"), fields=["effort_level"]
        )
        assert [call.kwargs["object"] for call in mock_crud.update.call_args_list] == [{"effort_level": "passive"}]

    @pytest.mark.asyncio
    async def test_llm_failure_retries_and_keeps_defaults(self):
        with (
            patch(f"{JOB_MODULE}.local_session") as mock_session_factory,
            patch(f"{JOB_MODULE}.crud_tasks") as mock_crud,
            patch(f"{JOB_MODULE}.call_task_field_guess_llm", new=AsyncMock(side_effect=RuntimeError("down"))),
        ):
            mock_session_factory.return_value.__aenter__.return_value = AsyncMock()
            mock_crud.get = AsyncMock(return_value=_task())
            mock_crud.update = AsyncMock()
            with pytest.raises(Retry):
                await guess_task_fields({"job_try": 1}, str(uuid7()), ["urgency"])
        mock_crud.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_deleted_task_is_noop(self):
        mock_crud, mock_llm = await self._run(None)
        mock_llm.assert_not_called()
        mock_crud.update.assert_not_called()


class TestWorkerRegistration:
    def test_guess_job_registered_with_bounded_retries(self):
        registered = {job.name: job for job in WorkerSettings.functions}  # type: ignore[attr-defined]
        assert registered["guess_task_fields"].max_tries == TASK_FIELD_GUESS_MAX_TRIES == 3
