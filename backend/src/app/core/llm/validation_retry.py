"""Loop B — schema-validation retry.

Separate from `retry.py`'s network-level retry loop: the call succeeded here, but the
response text didn't parse into the expected shape. Retries the same tier up to
`max_corrective_retries` more times, feeding the validation error back into the
conversation so the model can self-correct.
"""

from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from .provider import LlmMessage, LlmProviderResponseFormat, LlmTier
from .service import LlmService

T = TypeVar("T")

DEFAULT_MAX_CORRECTIVE_RETRIES = 2


async def run_with_validation_retry(
    llm_service: LlmService,
    tier: LlmTier,
    messages: list[LlmMessage],
    response_format: LlmProviderResponseFormat,
    validate: Callable[[str], T],
    max_corrective_retries: int = DEFAULT_MAX_CORRECTIVE_RETRIES,
) -> T:
    current_messages = list(messages)
    last_error: Exception | None = None
    for _attempt in range(max_corrective_retries + 1):
        result = await llm_service.complete(tier=tier, messages=current_messages, response_format=response_format)
        try:
            return validate(result.text)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            current_messages = current_messages + [
                LlmMessage(role="assistant", content=result.text),
                LlmMessage(
                    role="user",
                    content=(
                        f"Your last response didn't match the expected format: {exc}. "
                        "Please try again, returning only the corrected structured output."
                    ),
                ),
            ]
    raise last_error  # type: ignore[misc]
