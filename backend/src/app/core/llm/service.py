"""The tier-facing choke point every LLM call in the app goes through.

No `organization_id`/budget parameter — budget gating was deliberately not ported this
slice (see decisions-log.md). No tier-to-tier or provider-to-provider fallback: if a call
fails, it fails.
"""

from .provider import (
    LlmCompletionResult,
    LlmMessage,
    LlmProvider,
    LlmProviderCompletionRequest,
    LlmProviderResponseFormat,
    LlmTier,
)


class LlmService:
    def __init__(self, providers: dict[LlmTier, LlmProvider]):
        self._providers = providers

    async def complete(
        self,
        tier: LlmTier,
        messages: list[LlmMessage],
        max_tokens: int | None = None,
        response_format: LlmProviderResponseFormat | None = None,
    ) -> LlmCompletionResult:
        provider = self._providers[tier]
        return await provider.complete(
            LlmProviderCompletionRequest(messages=messages, max_tokens=max_tokens, response_format=response_format)
        )


# Built at startup in core/setup.py via build_llm_provider for each of the three tiers —
# same lifecycle pattern as core/utils/queue.py's `pool` global.
llm_service: LlmService | None = None
