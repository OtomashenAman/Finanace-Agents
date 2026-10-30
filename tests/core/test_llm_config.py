from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from src.app.core.config import Settings
from src.app.core.llm.anthropic_claude import AnthropicClaudeProvider
from src.app.core.llm.azure_openai import AzureOpenAIProvider
from src.app.core.llm.base import LLMError, LLMUsage

AZURE_VARS = (
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
)


@pytest.fixture(autouse=True)
def _no_azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AZURE_VARS:
        monkeypatch.delenv(name, raising=False)


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, database_url="postgresql+asyncpg://x", secret_key="k", **values)  # type: ignore[arg-type]


def test_azure_provider_requires_its_settings() -> None:
    with pytest.raises(ValidationError, match="AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT"):
        settings(llm_provider="azure_openai")


def test_disabled_provider_needs_nothing() -> None:
    assert settings(llm_provider="none").llm_provider == "none"


def test_azure_provider_is_built_from_settings() -> None:
    s = settings(
        llm_provider="azure_openai",
        azure_openai_api_key="sk-test-9f8e7d",
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_deployment="gpt-4.1-mini",
    )
    assert s.azure_openai_api_key is not None
    provider = AzureOpenAIProvider(
        api_key=s.azure_openai_api_key.get_secret_value(),
        endpoint=s.azure_openai_endpoint or "",
        api_version=s.azure_openai_api_version,
        deployment=s.azure_openai_deployment or "",
        timeout_seconds=s.llm_timeout_seconds,
        max_output_tokens=s.llm_max_output_tokens,
    )
    assert (provider.name, provider.model) == ("azure_openai", "gpt-4.1-mini")
    assert "sk-test-9f8e7d" not in repr(s)  # key never leaks into logs


# --- Anthropic Claude ---------------------------------------------------------------------


class Answer(BaseModel):
    summary: str


def claude(**overrides: Any) -> AnthropicClaudeProvider:
    values: dict[str, Any] = {
        "api_key": "sk-ant-test",
        "model": "claude-opus-5-5",
        "effort": "medium",
        "timeout_seconds": 5,
        "max_output_tokens": 16000,
    } | overrides
    return AnthropicClaudeProvider(**values)


def reply(stop_reason: str = "end_turn", parsed: Any = None, **extra: Any) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=900, output_tokens=120, cache_read_input_tokens=800)
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=extra.get("stop_details"),
        parsed_output=parsed,
        model="claude-opus-5-5",
        usage=usage,
        _request_id="req_011",
    )


def test_anthropic_provider_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        settings(llm_provider="anthropic")
    assert settings(llm_provider="anthropic", anthropic_api_key="k").anthropic_model == (
        "claude-opus-5-5"
    )


async def test_anthropic_output_is_parsed_with_usage_and_request_id() -> None:
    provider = claude()
    sent: dict[str, Any] = {}

    async def parse(**kwargs: Any) -> SimpleNamespace:
        sent.update(kwargs)
        return reply(parsed=Answer(summary="Matches the PO"))

    provider._client.messages.parse = parse  # type: ignore[method-assign]
    result = await provider.generate_structured(system="rules", user="{}", schema=Answer)

    assert result.output == Answer(summary="Matches the PO")
    assert (result.provider, result.model, result.request_id) == (
        "anthropic",
        "claude-opus-5-5",
        "req_011",
    )
    assert result.usage == LLMUsage(input_tokens=900, output_tokens=120, cached_tokens=800)
    assert sent["output_format"] is Answer and sent["output_config"] == {"effort": "medium"}
    assert sent["system"] == "rules" and sent["max_tokens"] == 16000


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (reply("refusal", stop_details=SimpleNamespace(category="cyber")), "declined"),
        (reply("max_tokens"), "cut off"),
        (reply("end_turn"), "no structured output"),
    ],
)
async def test_anthropic_failures_become_llm_errors(response: Any, message: str) -> None:
    provider = claude()

    async def parse(**kwargs: Any) -> Any:
        return response

    provider._client.messages.parse = parse  # type: ignore[method-assign]
    with pytest.raises(LLMError, match=message):
        await provider.generate_structured(system="s", user="u", schema=Answer)
