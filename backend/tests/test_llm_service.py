"""Fake LlmProvider implementations (plain classes conforming to the Protocol,
not the real HTTP adapters) assigned to high/medium/low."""

import pytest

from src.app.core.llm.provider import LlmCompletionResult, LlmMessage, LlmProviderCompletionRequest, LlmUsage
from src.app.core.llm.service import LlmService


class FakeProvider:
    def __init__(self, provider_name: str, raise_error: Exception | None = None):
        self.provider_name = provider_name
        self.raise_error = raise_error
        self.received_request: LlmProviderCompletionRequest | None = None

    async def complete(self, request: LlmProviderCompletionRequest) -> LlmCompletionResult:
        self.received_request = request
        if self.raise_error:
            raise self.raise_error
        return LlmCompletionResult(
            text=f"response from {self.provider_name}",
            model="fake-model",
            provider=self.provider_name,
            usage=LlmUsage(prompt_tokens=1, completion_tokens=1),
        )


class TestLlmService:
    @pytest.mark.asyncio
    async def test_complete_calls_the_requested_tier_only(self):
        high, medium, low = FakeProvider("high"), FakeProvider("medium"), FakeProvider("low")
        service = LlmService(providers={"high": high, "medium": medium, "low": low})

        result = await service.complete(tier="high", messages=[LlmMessage(role="user", content="hi")])

        assert result.text == "response from high"
        assert high.received_request is not None
        assert medium.received_request is None
        assert low.received_request is None

    @pytest.mark.asyncio
    async def test_provider_error_propagates_unchanged_no_fallback(self):
        error = RuntimeError("provider exploded")
        high = FakeProvider("high", raise_error=error)
        service = LlmService(providers={"high": high})

        with pytest.raises(RuntimeError, match="provider exploded"):
            await service.complete(tier="high", messages=[LlmMessage(role="user", content="hi")])
