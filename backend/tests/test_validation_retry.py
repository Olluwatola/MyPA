"""A validate callable that fails twice then succeeds, and one that never succeeds."""

from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel, ValidationError

from src.app.core.llm.provider import LlmCompletionResult, LlmMessage, LlmProviderResponseFormat, LlmUsage
from src.app.core.llm.service import LlmService
from src.app.core.llm.validation_retry import run_with_validation_retry


class DummySchema(BaseModel):
    value: str


def make_result(text: str) -> LlmCompletionResult:
    return LlmCompletionResult(
        text=text, model="fake", provider="fake", usage=LlmUsage(prompt_tokens=1, completion_tokens=1)
    )


class TestRunWithValidationRetry:
    @pytest.mark.asyncio
    async def test_succeeds_after_two_failures_three_total_calls(self):
        service = AsyncMock(spec=LlmService)
        service.complete = AsyncMock(
            side_effect=[make_result("not json"), make_result("still not json"), make_result('{"value": "ok"}')]
        )

        result = await run_with_validation_retry(
            llm_service=service,
            tier="high",
            messages=[LlmMessage(role="user", content="hi")],
            response_format=LlmProviderResponseFormat(name="dummy", schema_=DummySchema.model_json_schema()),
            validate=DummySchema.model_validate_json,
        )

        assert result.value == "ok"
        assert service.complete.call_count == 3

        second_call_messages = service.complete.call_args_list[1].kwargs["messages"]
        assert any("didn't match the expected format" in m.content for m in second_call_messages)

    @pytest.mark.asyncio
    async def test_raises_last_validation_error_after_exhausting_retries(self):
        service = AsyncMock(spec=LlmService)
        service.complete = AsyncMock(return_value=make_result("never valid"))

        with pytest.raises(ValidationError):
            await run_with_validation_retry(
                llm_service=service,
                tier="high",
                messages=[LlmMessage(role="user", content="hi")],
                response_format=LlmProviderResponseFormat(name="dummy", schema_=DummySchema.model_json_schema()),
                validate=DummySchema.model_validate_json,
            )

        assert service.complete.call_count == 3  # 1 initial + 2 corrective retries
