from pydantic import BaseModel

from src.app.core.llm.base import LLMNotConfiguredError, LLMResult


class DisabledProvider:
    """LLM_PROVIDER=none: features keep working, narratives are marked "not configured"."""

    name = "none"
    model = "none"

    async def generate_structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> LLMResult[T]:
        raise LLMNotConfiguredError("No LLM provider configured (LLM_PROVIDER=none)")
