import time
from typing import Literal

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import OutputConfigParam
from pydantic import BaseModel

from src.app.core.llm.base import LLMError, LLMResult, LLMUsage

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AnthropicClaudeProvider:
    """Anthropic Claude (Messages API) with output parsed and validated against the schema."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        effort: Effort,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self.model = model
        self._output_config: OutputConfigParam = {"effort": effort}
        self._max_output_tokens = max_output_tokens
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout_seconds, max_retries=2)

    async def generate_structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> LLMResult[T]:
        started = time.perf_counter()
        try:
            message = await self._client.messages.parse(
                model=self.model,
                max_tokens=self._max_output_tokens,
                # Stable system prompt first, so repeated runs of an agent share the cached prefix
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config=self._output_config,  # parse() adds the schema as its format
            )
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Provider returned HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise LLMError("Could not reach the LLM provider") from exc

        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            raise LLMError(f"Model declined the request ({category or 'no category'})")
        if message.stop_reason == "max_tokens":
            raise LLMError("Output was cut off (max output tokens reached)")
        if message.parsed_output is None:
            raise LLMError("Model returned no structured output")

        usage = message.usage
        return LLMResult(
            output=message.parsed_output,
            provider=self.name,
            model=message.model or self.model,
            request_id=getattr(message, "_request_id", None),  # set per response by the SDK
            usage=LLMUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.cache_read_input_tokens,
            ),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
