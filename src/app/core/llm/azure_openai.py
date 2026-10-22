import time

import openai
from openai import AsyncAzureOpenAI
from pydantic import BaseModel

from src.app.core.llm.base import LLMError, LLMResult, LLMUsage


class AzureOpenAIProvider:
    """Azure OpenAI chat completions with schema-validated structured output."""

    name = "azure_openai"

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        api_version: str,
        deployment: str,
        timeout_seconds: float,
        max_output_tokens: int,
    ) -> None:
        self.model = deployment
        self._max_output_tokens = max_output_tokens
        self._client = AsyncAzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            timeout=timeout_seconds,
            max_retries=2,
        )

    async def generate_structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> LLMResult[T]:
        started = time.perf_counter()
        try:
            completion = await self._client.chat.completions.parse(
                model=self.model,
                messages=[
                    # Stable system prompt first: Azure caches long identical prefixes
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                max_completion_tokens=self._max_output_tokens,
                temperature=0,
            )
        except openai.LengthFinishReasonError as exc:
            raise LLMError("Output was cut off (max output tokens reached)") from exc
        except openai.ContentFilterFinishReasonError as exc:
            raise LLMError("Blocked by the provider's content filter") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"Provider returned HTTP {exc.status_code}") from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise LLMError("Could not reach the LLM provider") from exc

        message = completion.choices[0].message
        if message.refusal:
            raise LLMError(f"Model refused: {message.refusal}")
        if message.parsed is None:
            raise LLMError("Model returned no structured output")

        usage = completion.usage
        details = usage.prompt_tokens_details if usage else None
        return LLMResult(
            output=message.parsed,
            provider=self.name,
            model=completion.model or self.model,
            request_id=getattr(completion, "_request_id", None),
            usage=LLMUsage(
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                cached_tokens=details.cached_tokens if details else None,
            ),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
