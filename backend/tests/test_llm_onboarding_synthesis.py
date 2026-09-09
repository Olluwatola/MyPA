"""Tests call_goal_synthesis_llm by mocking `llm_service.complete` (run_with_validation_
retry's actual dependency) — same convention as test_llm_extraction.py."""

from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.llm import service as llm_service_module
from src.app.core.llm.onboarding_synthesis import call_goal_synthesis_llm
from src.app.core.llm.provider import LlmCompletionResult, LlmUsage
from src.app.core.llm.service import LlmService

VALID_SYNTHESIS_JSON = (
    '{"suggested_goals": [{"title": "Finish the Q3 report", "description": null, "horizon": "short_term"}]}'
)


class TestCallGoalSynthesisLlm:
    @pytest.mark.asyncio
    async def test_calls_medium_tier_and_parses_result(self):
        fake_service = AsyncMock(spec=LlmService)
        fake_service.complete = AsyncMock(
            return_value=LlmCompletionResult(
                text=VALID_SYNTHESIS_JSON,
                model="fake",
                provider="fake",
                usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
            )
        )

        with patch.object(llm_service_module, "llm_service", fake_service):
            result = await call_goal_synthesis_llm([("email", "Recurring thread about the Q3 report")])

        assert result.suggested_goals[0].title == "Finish the Q3 report"
        fake_service.complete.assert_called_once()
        assert fake_service.complete.call_args.kwargs["tier"] == "medium"

    @pytest.mark.asyncio
    async def test_raises_if_llm_service_not_initialized(self):
        with patch.object(llm_service_module, "llm_service", None):
            with pytest.raises(AssertionError):
                await call_goal_synthesis_llm([("email", "some summary")])
