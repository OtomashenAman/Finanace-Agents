import pytest
from pydantic import ValidationError

from src.app.core.config import Settings
from src.app.core.llm.azure_openai import AzureOpenAIProvider

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
