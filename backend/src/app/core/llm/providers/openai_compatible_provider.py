"""One adapter covers OpenAI itself, Azure OpenAI, OpenRouter, or a local runner
(Ollama/vLLM/LM Studio) — swapped purely via `base_url`/`api_key`/`model` at
construction. Structured output maps to the native `response_format: {type:
"json_schema", ...}` mechanism."""

from typing import Any

import httpx

from ...exceptions.http_exceptions import UnprocessableEntityException
from ..errors import raise_for_llm_status
from ..provider import LlmCompletionResult, LlmProviderCompletionRequest, LlmUsage
from ..retry import execute_with_retry


class OpenAiCompatibleLlmProvider:
    def __init__(self, base_url: str, api_key: str, model: str, provider_label: str = "openai_compatible"):
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._provider_label = provider_label

    async def complete(self, request: LlmProviderCompletionRequest) -> LlmCompletionResult:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.response_format:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": request.response_format.name, "schema": request.response_format.schema_},
            }

        # One client for the whole retry sequence — a fresh AsyncClient (and a fresh TCP/
        # TLS handshake) per attempt would defeat the point of retrying quickly.
        async with httpx.AsyncClient() as client:

            async def _post() -> httpx.Response:
                return await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "content-type": "application/json"},
                    json=body,
                    timeout=60.0,
                )

            response = await execute_with_retry(_post)

        raise_for_llm_status(response, self._provider_label)
        data = response.json()

        choices = data.get("choices") or []
        if not choices:
            raise UnprocessableEntityException(
                f"{self._provider_label} response had no choices (e.g. a content-filtered response)"
            )

        return LlmCompletionResult(
            text=choices[0]["message"]["content"] or "",
            model=data.get("model", self._model),
            provider=self._provider_label,
            usage=LlmUsage(
                prompt_tokens=data["usage"]["prompt_tokens"],
                completion_tokens=data["usage"]["completion_tokens"],
            ),
        )
