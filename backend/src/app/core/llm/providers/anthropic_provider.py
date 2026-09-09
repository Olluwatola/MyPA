"""Anthropic adapter — hand-rolled `httpx` calls, no `anthropic` SDK dependency.

Structured output is achieved via a forced single tool-call: when `response_format` is
set, a single tool matching its `name`/`schema_` is declared and `tool_choice` forces the
model to call exactly that tool, so the tool's `input` is the structured payload.
"""

import json
from typing import Any

import httpx

from ...exceptions.http_exceptions import UnprocessableEntityException
from ..errors import raise_for_llm_status
from ..provider import (
    LlmCompletionResult,
    LlmMessage,
    LlmProviderCompletionRequest,
    LlmProviderResponseFormat,
    LlmUsage,
)
from ..retry import execute_with_retry

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicLlmProvider:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    async def complete(self, request: LlmProviderCompletionRequest) -> LlmCompletionResult:
        system, messages = self._split_system_messages(request.messages)
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if request.response_format:
            body["tools"] = [
                {
                    "name": request.response_format.name,
                    "input_schema": request.response_format.schema_,
                }
            ]
            body["tool_choice"] = {"type": "tool", "name": request.response_format.name}

        # One client for the whole retry sequence — a fresh AsyncClient (and a fresh TCP/
        # TLS handshake) per attempt would defeat the point of retrying quickly.
        async with httpx.AsyncClient() as client:

            async def _post() -> httpx.Response:
                return await client.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": ANTHROPIC_API_VERSION,
                        "content-type": "application/json",
                    },
                    json=body,
                    timeout=60.0,
                )

            response = await execute_with_retry(_post)

        raise_for_llm_status(response, "Anthropic")
        data = response.json()

        text = self._extract_text(data, request.response_format)
        return LlmCompletionResult(
            text=text,
            model=data.get("model", self._model),
            provider="anthropic",
            usage=LlmUsage(
                prompt_tokens=data["usage"]["input_tokens"],
                completion_tokens=data["usage"]["output_tokens"],
            ),
        )

    @staticmethod
    def _split_system_messages(messages: list[LlmMessage]) -> tuple[str | None, list[dict[str, str]]]:
        """Anthropic doesn't accept a `system`-role message inside `messages` — it's a
        separate top-level field."""
        system_parts = [m.content for m in messages if m.role == "system"]
        remaining = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        system = "\n\n".join(system_parts) if system_parts else None
        return system, remaining

    @staticmethod
    def _extract_text(data: dict[str, Any], response_format: LlmProviderResponseFormat | None) -> str:
        """Returns the assistant's plain text normally, or — when `response_format` was
        set — finds the `tool_use` content block and JSON-stringifies its `input` back
        into `.text`, so callers get a uniform "JSON text to parse" contract regardless
        of which adapter answered."""
        content_blocks: list[dict[str, Any]] = data.get("content", [])
        if response_format:
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    return json.dumps(block.get("input", {}))
            raise UnprocessableEntityException("Anthropic response did not contain the expected tool_use block")

        for block in content_blocks:
            if block.get("type") == "text":
                return str(block.get("text", ""))
        return ""
