"""Financial Reporting rules: opening a case on a report month, the aging scope task, what
blocks the Controller and CFO sign-offs, where a case stands, and the pack's distribution."""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import get_settings
from src.app.core.llm.base import LLMProvider
from src.app.service_pod.common import selection
from src.app.service_pod.common.ai import Fact
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.models import (
    CaseStatus,
    PodApproval,
    PodCase,
    ReviewTaskKind,
)
from src.app.service_pod.core.cases.service import Ctx, current_fingerprint
from src.app.service_pod.core.hooks import Composed
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.flows.fpa_trend import service as fpa
from src.app.service_pod.flows.reporting import engine
from src.app.service_pod.flows.reporting.models import PodReportPack
from src.app.service_pod.flows.reporting.schemas import ReportingSelection

DISTRIBUTION = "pack_distribution"
PURPOSES = {DISTRIBUTION: "Send the management pack to internal recipients"}
SCOPE_SUBJECT = "AR aging date"


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    sel = selection.parse_selection(ReportingSelection, case.selection)
    pack = plain(engine.compute(doc, sel))
    previous = case.state or {}
    kept = {k: previous[k] for k in fpa.KEPT_ON_REFRESH if k in previous}
    if refresh and fpa.figures(previous) == fpa.figures(pack):
        kept |= {
            k: previous[k] for k in ("commentary", "follow_ups", "mapping_review") if k in previous
        }
    case.state = {**pack, **kept}
    if refresh:
        await ensure_scope_task(session, case)


async def ensure_scope_task(session: AsyncSession, case: PodCase) -> None:
    """Aging as of another date than the month end: the Controller resolves it with evidence
    or keeps it as a disclosed limitation (TDD). Raised once per such source."""
    aging = case.state.get("aging") or {}
    if aging.get("matches_month_end", True):
        return
    detail = (
        f"AR aging is as of {aging['as_of']}, not the month end {aging['month_end']}: the "
        "balances are current, not month-end. Settle it with evidence (e.g. a month-end aging "
        "report) or keep it as a disclosed limitation of the pack."
    )
    open_same = [t for t in await system.open_tasks(session, case) if t.subject == SCOPE_SUBJECT]
    if not open_same:
        system.raise_task(session, case, ReviewTaskKind.SCOPE, detail, subject=SCOPE_SUBJECT)


async def after_create(session: AsyncSession, case: PodCase) -> None:
    await ensure_scope_task(session, case)


async def blockers(c: Ctx) -> list[str]:
    if c.case.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED):
        return []
    problems = list(engine.blocking(c.case.state))
    if not c.case.state.get("commentary"):
        problems.append("Write the pack's commentary first: draft it with AI or write it by hand.")
    problems.extend(await fpa.correction_problems(c.session, c.case))
    return problems


async def current_pack(session: AsyncSession, case: PodCase) -> PodReportPack | None:
    fingerprint = await current_fingerprint(session, case)
    return await session.scalar(
        select(PodReportPack)
        .where(PodReportPack.case_id == case.id, PodReportPack.content_hash == fingerprint)
        .order_by(PodReportPack.number.desc())
        .limit(1)
    )


async def completion_blockers(session: AsyncSession, case: PodCase) -> list[str]:
    problems = await fpa.correction_problems(session, case)
    if case.status == CaseStatus.APPROVED and await current_pack(session, case) is None:
        problems.append("Export the CFO-approved PDF pack first.")
    return problems


async def _signed(session: AsyncSession, case: PodCase) -> set[str]:
    fingerprint = await current_fingerprint(session, case)
    rows = await session.scalars(
        select(PodApproval.capacity).where(
            PodApproval.case_id == case.id, PodApproval.content_hash == fingerprint
        )
    )
    return set(rows)


async def stage(session: AsyncSession, case: PodCase) -> str:
    """controls -> statements -> controller -> cfo, as the case page's steps."""
    if case.status == CaseStatus.APPROVED:
        return "cfo"
    if engine.blocking(case.state):
        return "controls"
    if not case.state.get("commentary"):
        return "statements"
    return "cfo" if "Controller" in await _signed(session, case) else "controller"


async def phase(session: AsyncSession, case: PodCase, blockers: list[str]) -> str:
    if engine.blocking(case.state):
        return "review"
    if not case.state.get("commentary"):
        return "analysis"
    return "review" if blockers else "ready"


async def summary(session: AsyncSession, case: PodCase) -> str | None:
    metrics = case.state.get("metrics") or []
    if not metrics:
        return None
    last = metrics[-1]
    m = last.get("margin_pct")
    return (
        f"{case.state.get('report_month')} pack · revenue {case.state.get('currency', '')} "
        f"{Decimal(last['revenue']):,.0f} · margin "
        + ("undefined" if m is None else f"{Decimal(m):.1f}%")
    )


def facts(state: dict[str, Any]) -> list[Fact]:
    """The trend facts plus the Balance Sheets, close status and aging."""
    cur = str(state.get("currency", ""))
    out = fpa.facts(state)
    for period, sheet in (state.get("balance_sheets") or {}).items():
        if not sheet:
            continue
        name = fpa.month_name(period)
        for key in ("assets", "liabilities", "equity"):
            out.append(
                Fact(
                    f"balance_sheet.{key}.{period}",
                    f"Total {key} {name}",
                    f"{cur} {Decimal(str(sheet[key])):,.0f}",
                )
            )
    close = state.get("close") or {}
    if close:
        out.append(Fact("close.status", "Period close", str(close.get("status") or "unknown")))
    aging = state.get("aging") or {}
    if aging:
        over = sum(
            (Decimal(str(b["amount"])) for b in aging["buckets"] if b["label"] in ("61-90", "90+")),
            Decimal(0),
        )
        out += [
            Fact(
                "aging.total",
                f"Open AR as of {aging['as_of']}",
                f"{cur} {Decimal(str(aging['total'])):,.0f}",
            ),
            Fact("aging.over_60", "Open AR more than sixty days overdue", f"{cur} {over:,.0f}"),
        ]
    return out


async def draft_blocker(session: AsyncSession, case: PodCase, purpose: str) -> str | None:
    if purpose != DISTRIBUTION:
        return None
    if case.status != CaseStatus.APPROVED:
        return "The pack is sent only after the CFO has signed it off."
    if await current_pack(session, case) is None:
        return "Export the PDF pack first: the email carries the exact saved file."
    if not get_settings().pod_internal_recipients:
        return "No internal recipients are configured (POD_INTERNAL_RECIPIENTS)."
    return None


async def compose(session: AsyncSession, case: PodCase, purpose: str, llm: LLMProvider) -> Composed:
    month = fpa.month_name(str(case.state.get("report_month", "")))
    recipients = get_settings().pod_internal_recipients
    pack = await current_pack(session, case)
    return Composed(
        to_email=recipients[0] if recipients else None,
        to_name=None,
        subject=f"Management pack {month} ({case.reference})",
        body=(
            f"Hello,\n\nAttached is the {month} management pack"
            + (f" (version {pack.number})" if pack else "")
            + ", signed off by the Controller and the CFO.\n\nRegards,"
        ),
        fact_block=None,
        ai_drafted=False,
        note="Attach the exported pack before sending.",
    )
