"""Same shape as test_anthropic_provider.py, asserting response_format maps to the
native `json_schema` response-format mechanism instead of a forced tool call."""

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from src.app.core.exceptions.http_exceptions import UnauthorizedException, UnprocessableEntityException
from src.app.core.llm.provider import LlmMessage, LlmProviderCompletionRequest, LlmProviderResponseFormat
from src.app.core.llm.providers.openai_compatible_provider import OpenAiCompatibleLlmProvider

SUCCESS_BODY = {
    "model": "gpt-5-mini",
    "choices": [{"message": {"content": "hello"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def make_response(status_code: int, json_body: dict) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=json_body)


def make_fake_async_client_class(mock_post: AsyncMock) -> type:
    """A minimal async-context-manager stand-in for httpx.AsyncClient that counts how
    many times it was *constructed* — patching `.post` alone can't tell a single reused
    client from a fresh one per retry attempt, since `.post` is a class attribute either
    way."""

    class FakeAsyncClient:
        instances_created = 0

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            FakeAsyncClient.instances_created += 1
            self.post = mock_post

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *exc_info: Any) -> None:
            return None

    return FakeAsyncClient


class TestOpenAiCompatibleLlmProviderRequestShape:
    @pytest.mark.asyncio
    async def test_plain_text_request_shape(self):
        provider = OpenAiCompatibleLlmProvider(
            base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5-mini", provider_label="openai"
        )
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        mock_post = AsyncMock(return_value=make_response(200, SUCCESS_BODY))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await provider.complete(request)

        assert result.text == "hello"
        assert result.provider == "openai"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 5

        call_args = mock_post.call_args
        assert call_args.args[0] == "https://api.openai.com/v1/chat/completions"
        assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
        body = call_args.kwargs["json"]
        assert body["messages"] == [{"role": "user", "content": "Hi"}]
        assert "response_format" not in body

    @pytest.mark.asyncio
    async def test_response_format_maps_to_native_json_schema(self):
        provider = OpenAiCompatibleLlmProvider(
            base_url="http://localhost:11434/v1", api_key="ollama", model="llama3.1:8b", provider_label="ollama"
        )
        response_format = LlmProviderResponseFormat(name="record_memory_extraction", schema_={"type": "object"})
        request = LlmProviderCompletionRequest(
            messages=[LlmMessage(role="user", content="Extract this")], response_format=response_format
        )

        mock_post = AsyncMock(return_value=make_response(200, SUCCESS_BODY))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await provider.complete(request)

        assert result.provider == "ollama"
        body = mock_post.call_args.kwargs["json"]
        assert body["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "record_memory_extraction", "schema": {"type": "object"}},
        }

    @pytest.mark.asyncio
    async def test_500_maps_to_bad_gateway(self):
        provider = OpenAiCompatibleLlmProvider(
            base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5-mini", provider_label="openai"
        )
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        mock_post = AsyncMock(return_value=make_response(500, {"error": "boom"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(HTTPException) as exc_info:
                await provider.complete(request)

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_401_maps_to_unauthorized(self):
        provider = OpenAiCompatibleLlmProvider(
            base_url="https://api.openai.com/v1", api_key="bad-key", model="gpt-5-mini", provider_label="openai"
        )
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        mock_post = AsyncMock(return_value=make_response(401, {"error": "invalid api key"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(UnauthorizedException):
                await provider.complete(request)

    @pytest.mark.asyncio
    async def test_empty_choices_raises_controlled_exception(self):
        provider = OpenAiCompatibleLlmProvider(
            base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5-mini", provider_label="openai"
        )
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        content_filtered_body = {
            "model": "gpt-5-mini",
            "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 0},
        }
        mock_post = AsyncMock(return_value=make_response(200, content_filtered_body))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(UnprocessableEntityException):
                await provider.complete(request)

    @pytest.mark.asyncio
    async def test_one_client_is_reused_across_retries(self):
        provider = OpenAiCompatibleLlmProvider(
            base_url="https://api.openai.com/v1", api_key="test-key", model="gpt-5-mini", provider_label="openai"
        )
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        responses = [make_response(429, {}), make_response(200, SUCCESS_BODY)]
        mock_post = AsyncMock(side_effect=responses)
        fake_client_class = make_fake_async_client_class(mock_post)
        with (
            patch("httpx.AsyncClient", fake_client_class),
            patch("src.app.core.llm.retry.anyio.sleep", AsyncMock()),
        ):
            await provider.complete(request)

        assert mock_post.call_count == 2
        assert fake_client_class.instances_created == 1
