"""Bounded AI for the Service POD: structured extraction and cited narrative.

The model never does accounting arithmetic or decides anything. Extraction output must pass
the workflow's validator (e.g. every amount appears in the quoted text) or the action stops;
there is no silent fallback. Narrative may only reference deterministic facts by ID and may
not contain numbers of its own, so it can't introduce an unsupported figure.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from src.app.core.errors import AppError
from src.app.core.llm.base import ImageInput, LLMProvider, LLMResult


class AiOutputRejectedError(AppError):
    """The model answered, but the answer failed validation: nothing was used."""

    status_code = 422
    code = "ai_output_rejected"


@dataclass(frozen=True)
class Provenance:
    provider: str
    model: str
    request_id: str | None
    prompt_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True)
class Extraction[T: BaseModel]:
    output: T
    provenance: Provenance


def _provenance(result: LLMResult[Any], prompt_version: str) -> Provenance:
    return Provenance(result.provider, result.model, result.request_id, prompt_version)


async def extract[T: BaseModel](
    llm: LLMProvider,
    *,
    system: str,
    user: str,
    schema: type[T],
    prompt_version: str,
    validate: Callable[[T], list[str]],
    images: Sequence[ImageInput] = (),
) -> Extraction[T]:
    """Structured output that also passes `validate` (a list of problems; empty = valid).
    LLMError from the provider propagates unchanged."""
    if images:
        result = await llm.generate_structured(
            system=system, user=user, schema=schema, images=images
        )
    else:
        result = await llm.generate_structured(system=system, user=user, schema=schema)
    problems = validate(result.output)
    if problems:
        raise AiOutputRejectedError(
            "the AI's reading didn't hold up against the reply: " + "; ".join(problems[:5])
        )
    return Extraction(result.output, _provenance(result, prompt_version))


# --- cited narrative -------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """A deterministic, already-calculated figure the narrative may refer to."""

    id: str  # e.g. "revenue.2026-09"
    label: str
    value: str  # formatted by the engine, never by the model


class Highlight(BaseModel):
    text: str = Field(description="One sentence; no digits, currency or percent signs")
    fact_ids: list[str] = Field(description="IDs of the facts this sentence relies on")


# Plain fields only (provider strict JSON schema); limits are checked in narrative_problems
class CitedNarrative(BaseModel):
    highlights: list[Highlight] = Field(description="At most 12 cited sentences")


MAX_HIGHLIGHTS = 12
NUMERIC = re.compile(r"[0-9$%€£₹]")
# Figures written out in words are still the model stating a number ("sixty thousand
# dollars", "one point seven percentage points"). Small counts ("led by two accounts")
# stay allowed, as do ordinary words like "one-time".
NUMBER_WORDS = re.compile(
    r"\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million"
    r"|billion|percent|percentage|dollars?|cents?|euros?|pounds?|rupees?)\b"
    r"|\bpoint (?:zero|one|two|three|four|five|six|seven|eight|nine)\b",
    re.IGNORECASE,
)


def states_number(text: str) -> bool:
    """True when prose states a figure itself (digits, currency or percent signs, or a
    number written in words) instead of citing a fact."""
    return bool(NUMERIC.search(text) or NUMBER_WORDS.search(text))


def narrative_problems(narrative: CitedNarrative, facts: list[Fact]) -> list[str]:
    known = {f.id for f in facts}
    problems = []
    if not 1 <= len(narrative.highlights) <= MAX_HIGHLIGHTS:
        problems.append(f"expected 1 to {MAX_HIGHLIGHTS} highlights")
    for i, h in enumerate(narrative.highlights, start=1):
        if not h.fact_ids:
            problems.append(f"highlight {i} cites no fact")
        unknown = [f for f in h.fact_ids if f not in known]
        if unknown:
            problems.append(f"highlight {i} cites unknown facts {', '.join(unknown)}")
        if states_number(h.text):
            problems.append(f"highlight {i} states a number itself instead of citing a fact")
    return problems


def facts_prompt(facts: list[Fact]) -> str:
    return "\n".join(f"- [{f.id}] {f.label}: {f.value}" for f in facts)


async def cited_narrative(
    llm: LLMProvider, *, system: str, facts: list[Fact], ask: str, prompt_version: str
) -> Extraction[CitedNarrative]:
    user = (
        f"{ask}\n\nFacts (cite their IDs; write no digits, currency or percent signs and no "
        f"numbers in words - the "
        f"figures are shown from the facts you cite):\n{facts_prompt(facts)}"
    )
    return await extract(
        llm,
        system=system,
        user=user,
        schema=CitedNarrative,
        prompt_version=prompt_version,
        validate=lambda n: narrative_problems(n, facts),
    )
