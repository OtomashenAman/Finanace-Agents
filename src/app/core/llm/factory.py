from functools import lru_cache

from src.app.core.config import get_settings
from src.app.core.llm.anthropic_claude import AnthropicClaudeProvider
from src.app.core.llm.azure_openai import AzureOpenAIProvider
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.disabled import DisabledProvider

ANTHROPIC_MIN_OUTPUT_TOKENS = 16_000


@lru_cache
def get_llm_provider() -> LLMProvider:
    """The configured provider (also a FastAPI dependency, so tests can override it)."""
    settings = get_settings()
    if settings.llm_provider == "anthropic":
        assert settings.anthropic_api_key is not None  # noqa: S101 - settings validation
        return AnthropicClaudeProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
            effort=settings.anthropic_effort,
            timeout_seconds=settings.llm_timeout_seconds,
            # Claude thinks before answering: thinking counts toward the output budget
            max_output_tokens=max(settings.llm_max_output_tokens, ANTHROPIC_MIN_OUTPUT_TOKENS),
        )
    if settings.llm_provider == "azure_openai":
        # Settings validation guarantees these are present
        assert settings.azure_openai_api_key is not None  # noqa: S101
        assert settings.azure_openai_endpoint is not None  # noqa: S101
        assert settings.azure_openai_deployment is not None  # noqa: S101
        return AzureOpenAIProvider(
            api_key=settings.azure_openai_api_key.get_secret_value(),
            endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
            deployment=settings.azure_openai_deployment,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    return DisabledProvider()
