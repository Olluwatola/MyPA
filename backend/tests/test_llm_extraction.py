"""Tests call_extraction_llm by mocking `llm_service.complete` (run_with_validation_
retry's actual dependency), not a raw Anthropic client — the tool-use-specific mocking
lives in test_anthropic_provider.py instead, since that's the layer that actually talks
tool-use."""

from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.llm import service as llm_service_module
from src.app.core.llm.extraction import call_extraction_llm
from src.app.core.llm.provider import LlmCompletionResult, LlmUsage
from src.app.core.llm.service import LlmService

VALID_EXTRACTION_JSON = (
    '{"summary": "Buy milk", "entities": [], "relationships": [], "goals": [], "preferences": [], "tasks": []}'
)


class TestCallExtractionLlm:
    @pytest.mark.asyncio
    async def test_calls_high_tier_and_parses_result(self):
        fake_service = AsyncMock(spec=LlmService)
        fake_service.complete = AsyncMock(
            return_value=LlmCompletionResult(
                text=VALID_EXTRACTION_JSON,
                model="fake",
                provider="fake",
                usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
            )
        )

        with patch.object(llm_service_module, "llm_service", fake_service):
            result = await call_extraction_llm("Remember to buy milk", [])

        assert result.summary == "Buy milk"
        fake_service.complete.assert_called_once()
        assert fake_service.complete.call_args.kwargs["tier"] == "high"

    @pytest.mark.asyncio
    async def test_raises_if_llm_service_not_initialized(self):
        with patch.object(llm_service_module, "llm_service", None):
            with pytest.raises(AssertionError):
                await call_extraction_llm("Remember to buy milk", [])

    @pytest.mark.asyncio
    async def test_open_goals_are_listed_with_numbers_in_the_prompt(self):
        fake_service = AsyncMock(spec=LlmService)
        fake_service.complete = AsyncMock(
            return_value=LlmCompletionResult(
                text=VALID_EXTRACTION_JSON,
                model="fake",
                provider="fake",
                usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
            )
        )
        goals = [{"title": "Launch ClientPal", "horizon": "short_term"}, {"title": "Run a marathon", "horizon": None}]

        with patch.object(llm_service_module, "llm_service", fake_service):
            await call_extraction_llm("Finish the landing page", goals)

        user_message = fake_service.complete.call_args.kwargs["messages"][1].content
        assert user_message.startswith("Finish the landing page")
        assert "[1] Launch ClientPal (short term)" in user_message
        assert "[2] Run a marathon" in user_message

    @pytest.mark.asyncio
    async def test_no_goal_block_without_open_goals(self):
        fake_service = AsyncMock(spec=LlmService)
        fake_service.complete = AsyncMock(
            return_value=LlmCompletionResult(
                text=VALID_EXTRACTION_JSON,
                model="fake",
                provider="fake",
                usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
            )
        )
        with patch.object(llm_service_module, "llm_service", fake_service):
            await call_extraction_llm("Buy milk", [])

        assert fake_service.complete.call_args.kwargs["messages"][1].content == "Buy milk"
