"""Mocks httpx.AsyncClient.post (not the whole client): asserts request shape (headers,
tools/tool_choice when response_format is given, system message extracted out of
messages), retry behavior (429 -> 200 is 2 calls; 500 is exactly 1 call, not retried),
one client reused across retries, and that different failure statuses map to different
exception types."""

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from src.app.core.exceptions.http_exceptions import RateLimitException, UnauthorizedException
from src.app.core.llm.provider import LlmMessage, LlmProviderCompletionRequest, LlmProviderResponseFormat
from src.app.core.llm.providers.anthropic_provider import AnthropicLlmProvider

SUCCESS_TEXT_BODY = {
    "model": "claude-opus-5",
    "content": [{"type": "text", "text": "hello"}],
    "usage": {"input_tokens": 10, "output_tokens": 5},
}

SUCCESS_TOOL_BODY = {
    "model": "claude-opus-5",
    "content": [{"type": "tool_use", "id": "abc", "name": "record_memory_extraction", "input": {"summary": "hi"}}],
    "usage": {"input_tokens": 10, "output_tokens": 5},
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


class TestAnthropicLlmProviderRequestShape:
    @pytest.mark.asyncio
    async def test_plain_text_request_shape_and_system_extraction(self):
        provider = AnthropicLlmProvider(api_key="test-key", model="claude-opus-5")
        request = LlmProviderCompletionRequest(
            messages=[
                LlmMessage(role="system", content="You are helpful."),
                LlmMessage(role="user", content="Hi"),
            ]
        )

        mock_post = AsyncMock(return_value=make_response(200, SUCCESS_TEXT_BODY))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await provider.complete(request)

        assert result.text == "hello"
        assert result.provider == "anthropic"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 5

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["headers"]["x-api-key"] == "test-key"
        assert call_kwargs["headers"]["anthropic-version"] == "2023-06-01"
        body = call_kwargs["json"]
        assert body["system"] == "You are helpful."
        assert body["messages"] == [{"role": "user", "content": "Hi"}]
        assert "tools" not in body

    @pytest.mark.asyncio
    async def test_response_format_sets_tools_and_tool_choice(self):
        provider = AnthropicLlmProvider(api_key="test-key", model="claude-opus-5")
        response_format = LlmProviderResponseFormat(name="record_memory_extraction", schema_={"type": "object"})
        request = LlmProviderCompletionRequest(
            messages=[LlmMessage(role="user", content="Extract this")],
            response_format=response_format,
        )

        mock_post = AsyncMock(return_value=make_response(200, SUCCESS_TOOL_BODY))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            result = await provider.complete(request)

        assert json.loads(result.text) == {"summary": "hi"}

        body = mock_post.call_args.kwargs["json"]
        assert body["tools"] == [{"name": "record_memory_extraction", "input_schema": {"type": "object"}}]
        assert body["tool_choice"] == {"type": "tool", "name": "record_memory_extraction"}


class TestAnthropicLlmProviderRetryBehavior:
    @pytest.mark.asyncio
    async def test_429_then_200_results_in_two_calls(self):
        provider = AnthropicLlmProvider(api_key="test-key", model="claude-opus-5")
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        responses = [make_response(429, {}), make_response(200, SUCCESS_TEXT_BODY)]
        mock_post = AsyncMock(side_effect=responses)
        with (
            patch.object(httpx.AsyncClient, "post", mock_post),
            patch("src.app.core.llm.retry.anyio.sleep", AsyncMock()),
        ):
            result = await provider.complete(request)

        assert result.text == "hello"
        assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_one_client_is_reused_across_retries(self):
        """A fresh AsyncClient (and a fresh TCP/TLS handshake) per attempt would defeat
        the point of retrying quickly — the client must be constructed once per
        complete() call, not once per attempt."""
        provider = AnthropicLlmProvider(api_key="test-key", model="claude-opus-5")
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        responses = [make_response(429, {}), make_response(200, SUCCESS_TEXT_BODY)]
        mock_post = AsyncMock(side_effect=responses)
        fake_client_class = make_fake_async_client_class(mock_post)
        with (
            patch("httpx.AsyncClient", fake_client_class),
            patch("src.app.core.llm.retry.anyio.sleep", AsyncMock()),
        ):
            await provider.complete(request)

        assert mock_post.call_count == 2
        assert fake_client_class.instances_created == 1

    @pytest.mark.asyncio
    async def test_500_is_not_retried_and_maps_to_bad_gateway(self):
        provider = AnthropicLlmProvider(api_key="test-key", model="claude-opus-5")
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        mock_post = AsyncMock(return_value=make_response(500, {"error": "boom"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(HTTPException) as exc_info:
                await provider.complete(request)

        assert exc_info.value.status_code == 502
        assert mock_post.call_count == 1

    @pytest.mark.asyncio
    async def test_401_maps_to_unauthorized(self):
        provider = AnthropicLlmProvider(api_key="bad-key", model="claude-opus-5")
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        mock_post = AsyncMock(return_value=make_response(401, {"error": "invalid x-api-key"}))
        with patch.object(httpx.AsyncClient, "post", mock_post):
            with pytest.raises(UnauthorizedException):
                await provider.complete(request)

    @pytest.mark.asyncio
    async def test_429_exhausted_maps_to_rate_limit(self):
        provider = AnthropicLlmProvider(api_key="test-key", model="claude-opus-5")
        request = LlmProviderCompletionRequest(messages=[LlmMessage(role="user", content="Hi")])

        mock_post = AsyncMock(return_value=make_response(429, {"error": "rate limited"}))
        with (
            patch.object(httpx.AsyncClient, "post", mock_post),
            patch("src.app.core.llm.retry.anyio.sleep", AsyncMock()),
        ):
            with pytest.raises(RateLimitException):
                await provider.complete(request)
