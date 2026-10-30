"""Drafting customer emails: the source's figures as a fixed table, AI wording around it
(never figures), and a labelled template when the AI can't help."""

from collections.abc import Sequence

from pydantic import BaseModel, Field

from src.app.core.config import get_settings
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.service_pod.common import ai
from src.app.service_pod.core.hooks import Composed

WORDING_PROMPT_VERSION = "pod_wording/v1"


def table(rows: Sequence[Sequence[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in rows)
    return "\n".join(line.rstrip() for line in lines)


class Wording(BaseModel):
    opening: str = Field(description="Greeting and one or two sentences of request; no figures")
    closing: str = Field(description="One or two closing sentences and a sign-off; no figures")


def _wording_problems(w: Wording) -> list[str]:
    problems = []
    for name, text in (("opening", w.opening), ("closing", w.closing)):
        if not text.strip():
            problems.append(f"{name} is empty")
        elif ai.NUMERIC.search(text):  # the same no-figures rule as cited narrative
            problems.append(f"{name} contains figures; they must come from the source only")
    return problems


async def compose(
    llm: LLMProvider,
    *,
    to_email: str | None,
    to_name: str | None,
    subject: str,
    fact_block: str,
    ask: str,
    template_opening: str,
    template_closing: str,
) -> Composed:
    """The fact block from the source between AI wording (no figures allowed in it). Without
    a working AI, a fixed template, labelled as such."""
    signature = get_settings().email_sender_name
    try:
        result = await ai.extract(
            llm,
            system=(
                "You write short, polite business emails for a finance team. Write only the "
                "opening and the closing; the invoice table is inserted between them by the "
                "system. Never write numbers, amounts, dates or invoice numbers yourself."
            ),
            user=f"Recipient: {to_name or 'the customer'}\nPurpose: {ask}\nSign as: {signature}",
            schema=Wording,
            prompt_version=WORDING_PROMPT_VERSION,
            validate=_wording_problems,
        )
        opening, closing, drafted, note = (
            result.output.opening.strip(),
            result.output.closing.strip(),
            True,
            None,
        )
    except (LLMError, ai.AiOutputRejectedError) as exc:
        opening, closing, drafted = template_opening, f"{template_closing}\n{signature}", False
        note = f"Template text (AI wording unavailable: {str(exc)[:120] or 'not configured'})."
    return Composed(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=f"{opening}\n\n{fact_block}\n\n{closing}",
        fact_block=fact_block,
        ai_drafted=drafted,
        note=note,
    )
