"""build_llm_provider against plain settings objects — a pure function, no mocking
needed."""

import pytest

from src.app.core.config import LlmTierSettings
from src.app.core.llm.factory import build_llm_provider
from src.app.core.llm.providers.anthropic_provider import AnthropicLlmProvider
from src.app.core.llm.providers.openai_compatible_provider import OpenAiCompatibleLlmProvider


class TestBuildLlmProvider:
    def test_anthropic_tier_builds_anthropic_provider(self):
        settings = LlmTierSettings(LLM_TIER_HIGH_PROVIDER="anthropic", ANTHROPIC_API_KEY="key")

        provider = build_llm_provider("high", settings)

        assert isinstance(provider, AnthropicLlmProvider)
        assert provider._model == settings.LLM_TIER_HIGH_ANTHROPIC_MODEL
        assert provider._api_key == "key"

    def test_openai_tier_builds_openai_compatible_provider(self):
        settings = LlmTierSettings(LLM_TIER_MEDIUM_PROVIDER="openai", OPENAI_API_KEY="key")

        provider = build_llm_provider("medium", settings)

        assert isinstance(provider, OpenAiCompatibleLlmProvider)
        assert provider._provider_label == "openai"
        assert provider._base_url == settings.OPENAI_BASE_URL
        assert provider._model == settings.LLM_TIER_MEDIUM_OPENAI_MODEL

    def test_ollama_tier_builds_openai_compatible_provider_with_ollama_base_url(self):
        settings = LlmTierSettings(LLM_TIER_LOW_PROVIDER="ollama")

        provider = build_llm_provider("low", settings)

        assert isinstance(provider, OpenAiCompatibleLlmProvider)
        assert provider._provider_label == "ollama"
        assert provider._base_url == settings.OLLAMA_BASE_URL
        assert provider._model == settings.LLM_TIER_LOW_OLLAMA_MODEL

    def test_unknown_provider_raises_value_error(self):
        settings = LlmTierSettings(LLM_TIER_HIGH_PROVIDER="bogus")

        with pytest.raises(ValueError, match="bogus"):
            build_llm_provider("high", settings)
