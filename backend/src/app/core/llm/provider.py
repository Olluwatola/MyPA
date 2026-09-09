"""The shared interface every LLM provider adapter implements.

`Protocol` (structural typing), not an ABC — matches this project's general preference
for lightweight interfaces over inheritance; both adapters in `providers/` satisfy this
without subclassing anything here.
"""

from typing import Literal, Protocol

from pydantic import BaseModel

LlmTier = Literal["high", "medium", "low"]
LlmRole = Literal["system", "user", "assistant"]


class LlmMessage(BaseModel):
    role: LlmRole
    content: str


class LlmUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int


class LlmProviderResponseFormat(BaseModel):
    name: str
    schema_: dict  # the output of a Pydantic model's `model_json_schema()`


class LlmProviderCompletionRequest(BaseModel):
    messages: list[LlmMessage]
    max_tokens: int | None = None
    response_format: LlmProviderResponseFormat | None = None


class LlmCompletionResult(BaseModel):
    text: str
    model: str
    provider: str
    usage: LlmUsage


class LlmProvider(Protocol):
    async def complete(self, request: LlmProviderCompletionRequest) -> LlmCompletionResult: ...
