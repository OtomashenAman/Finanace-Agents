from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """The provider failed (network, refusal, invalid output...). Callers degrade gracefully."""


class LLMNotConfiguredError(LLMError):
    """No provider configured (LLM_PROVIDER=none)."""


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    provider: str
    model: str
    request_id: str | None
    usage: LLMUsage
    latency_ms: int


class LLMProvider(Protocol):
    """Everything features need from an LLM. Add providers by implementing this."""

    name: str
    model: str

    async def generate_structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> LLMResult[T]:
        """Return output validated against `schema`, or raise LLMError."""
        ...
