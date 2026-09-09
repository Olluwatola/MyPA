"""Builds a concrete `LlmProvider` for a given tier from config.

Same `OpenAiCompatibleLlmProvider` class serves both the `openai` and `ollama` provider
profiles — only `base_url`/`api_key`/`provider_label` differ, treating "OpenAI" and "a
local runner" as two configurations of one adapter, not two adapters.
"""

from ..config import LlmTierSettings
from .provider import LlmProvider, LlmTier
from .providers.anthropic_provider import AnthropicLlmProvider
from .providers.openai_compatible_provider import OpenAiCompatibleLlmProvider


def build_llm_provider(tier: LlmTier, settings: LlmTierSettings) -> LlmProvider:
    tier_upper = tier.upper()
    provider_name = getattr(settings, f"LLM_TIER_{tier_upper}_PROVIDER")

    if provider_name == "anthropic":
        model = getattr(settings, f"LLM_TIER_{tier_upper}_ANTHROPIC_MODEL")
        return AnthropicLlmProvider(api_key=settings.ANTHROPIC_API_KEY.get_secret_value(), model=model)

    if provider_name == "openai":
        model = getattr(settings, f"LLM_TIER_{tier_upper}_OPENAI_MODEL")
        return OpenAiCompatibleLlmProvider(
            base_url=settings.OPENAI_BASE_URL,
            api_key=settings.OPENAI_API_KEY.get_secret_value(),
            model=model,
            provider_label="openai",
        )

    if provider_name == "ollama":
        model = getattr(settings, f"LLM_TIER_{tier_upper}_OLLAMA_MODEL")
        return OpenAiCompatibleLlmProvider(
            base_url=settings.OLLAMA_BASE_URL,
            api_key=settings.OLLAMA_API_KEY.get_secret_value(),
            model=model,
            provider_label="ollama",
        )

    raise ValueError(f"Unknown LLM provider '{provider_name}' for tier '{tier}'")
