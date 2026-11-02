"""The Finance Head commentary drafted by AI: a few findings and at most three follow-ups
(open questions or checks), each citing the engine's facts. The model never states a figure
itself (TDD: no digits, currency or percent signs); the screen shows the cited values."""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.service_pod.common import ai
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.exceptions import CaseActionError
from src.app.service_pod.core.cases.models import CaseStatus
from src.app.service_pod.core.cases.schemas import CaseDetail
from src.app.service_pod.core.cases.service import get_case
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.fpa_trend.schemas import AiStatement, FpaCommentary
from src.app.service_pod.flows.fpa_trend.service import facts

PROMPT_VERSION = "fpa_commentary/v3"
# Short on purpose: the Finance Head reads the findings, the screens hold the detail
MAX = {"highlights": 4, "follow_ups": 3}

SYSTEM = (
    "You are an FP&A analyst writing for {audience}. You explain month-on-month "
    "movements in revenue, costs and operating margin using only the facts given, citing their "
    "IDs. Write no digits, currency or percent signs, and no amounts in words either (not "
    "'sixty thousand', 'ten percent', 'one point seven points'): say rose, fell, the largest, "
    "partly offset, and cite the fact; its figure is shown beside your sentence. Refer to "
    "months by name only (August, September), never as dates or with a year. Name the "
    "customers, vendors and accounts the facts name. Don't speculate about causes the facts "
    "don't show: ask an open question instead. Be brief: only what matters, never a line that "
    "is zero or unchanged, and cite at most three facts per sentence."
)
ASK = (
    "Write two to four findings about the latest month against the month before: what moved "
    "and which contributors explain it (use the trend facts only if the longer trend matters). "
    "Then at most three follow-ups: open questions the figures can't answer (e.g. whether new "
    "revenue is recurring) or checks to make. Mention a data caveat only if it changes the "
    "reading. The sign-off is separate: don't suggest approving the commentary."
)


# Which workflows have this commentary: their facts and who reads it (Reporting registers too)
_WRITERS: dict[WorkflowKey, tuple[Callable[[dict[str, Any]], list[ai.Fact]], str]] = {
    WorkflowKey.FPA_TREND: (facts, "the Finance Head"),
}


def register(
    key: WorkflowKey, facts_for: Callable[[dict[str, Any]], list[ai.Fact]], audience: str
) -> None:
    _WRITERS[key] = (facts_for, audience)


class CommentaryUnavailableError(AppError):
    status_code = 422
    code = "commentary_unavailable"


NAMES = {"highlights": "finding", "follow_ups": "follow-up"}
ATTEMPTS = 2  # a rejected draft is retried once, told what was wrong; never let through


def problems(out: FpaCommentary, known: set[str]) -> list[str]:
    found = []
    for part, limit in MAX.items():
        items: list[AiStatement] = getattr(out, part)
        name = NAMES[part]
        if len(items) > limit:
            found.append(f"more than {limit} {part}")
        for i, item in enumerate(items, start=1):
            if not item.fact_ids:
                found.append(f"{name} {i} cites no fact")
            unknown = [f for f in item.fact_ids if f not in known]
            if unknown:
                found.append(f"{name} {i} cites unknown facts {', '.join(unknown)}")
            if ai.states_number(item.text):
                found.append(f"{name} {i} states a figure itself ({item.text[:80]!r})")
    if not out.highlights:
        found.append("no findings")
    return found


async def draft_commentary(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    expected_version: int,
    llm: LLMProvider,
) -> CaseDetail:
    case = await load_case(session, case_id, lock=True, expected_version=expected_version)
    writer = _WRITERS.get(case.workflow)
    if writer is None:
        raise CaseActionError("This workflow has no cited commentary.")
    facts_for, audience = writer
    if case.status != CaseStatus.DRAFT:
        raise CaseActionError(f"Can't change the commentary while the case is {case.status.value}.")
    if [i for i in case.state.get("issues", []) if i.get("blocking")]:
        raise CaseActionError("Settle the data issues first: commentary on them would mislead.")
    cited = facts_for(case.state)
    known = {f.id for f in cited}
    user = f"{ASK}\n\nFacts:\n{ai.facts_prompt(cited)}"
    rejected = ""
    for _ in range(ATTEMPTS):
        try:
            result = await ai.extract(
                llm,
                system=SYSTEM.format(audience=audience),
                user=user + rejected,
                schema=FpaCommentary,
                prompt_version=PROMPT_VERSION,
                validate=lambda out: problems(out, known),
            )
            break
        except ai.AiOutputRejectedError as exc:
            why = exc.message.split(": ", 1)[-1]
            rejected = (
                f"\n\nYour previous draft was rejected: {why}. Rewrite it citing the facts, "
                "with no figures at all: no digits (months by name only, e.g. 'August to "
                "September', no years) and no amounts or percentages in words."
            )
        except LLMError as exc:
            raise CommentaryUnavailableError(
                "The AI service didn't answer. Try again, or write the commentary by hand."
            ) from exc
    else:
        raise CommentaryUnavailableError(
            f"The AI draft didn't pass the checks twice ({why}). Try again, or write the "
            "commentary by hand."
        )
    out = result.output
    case.state = plain(
        {
            **case.state,
            "commentary": {
                "by": "ai",
                "written_at": utcnow(),
                "highlights": [h.model_dump() for h in out.highlights],
                "facts": [vars(f) for f in cited],
                "provenance": result.provenance.as_dict(),
            },
            # Questions and checks stay with the commentary: they don't block the sign-off
            # and aren't review tasks; one can be tracked as an owned action
            "follow_ups": [f.model_dump() for f in out.follow_ups],
            "recommended_actions": None,
        }
    )
    system.bump_case(
        session, case, "pod.fpa_commentary", "AI drafted the commentary", actor_id=access.user.id
    )
    await session.commit()
    return await get_case(session, access, case.id)
