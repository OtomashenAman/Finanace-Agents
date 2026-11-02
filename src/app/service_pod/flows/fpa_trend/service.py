"""FP&A rules: opening a case on a period, what blocks the Finance Head sign-off, where a
case stands, and how a posted correction is proven by a fresh source."""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.common import selection
from src.app.service_pod.common.ai import Fact
from src.app.service_pod.common.canonical import plain
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.cases.service import Ctx
from src.app.service_pod.core.snapshots.contract import AccountClass, SnapshotDocument
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus
from src.app.service_pod.flows.fpa_trend import engine
from src.app.service_pod.flows.fpa_trend.schemas import FpaSelection

# What a manual analysis keeps when the case moves to a newer source
KEPT_ON_REFRESH = ("corrections",)
# How a journal line moves the P&L figure of its account (P&L shows income and costs positive)
CREDIT_RAISES = {AccountClass.INCOME, AccountClass.OTHER_INCOME}
PNL = {
    AccountClass.INCOME,
    AccountClass.COST_OF_GOODS_SOLD,
    AccountClass.EXPENSE,
    AccountClass.OTHER_INCOME,
    AccountClass.OTHER_EXPENSE,
}


def figures(state: dict[str, Any]) -> dict[str, Any]:
    """The computed part of the state (what commentary and approvals are about)."""
    return {k: state.get(k) for k in ("months", "metrics", "changes", "issues")}


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    sel = selection.parse_selection(FpaSelection, case.selection)
    pack = plain(engine.compute(doc, sel))
    previous = case.state or {}
    kept = {k: previous[k] for k in KEPT_ON_REFRESH if k in previous}
    if refresh and figures(previous) == figures(pack):
        # Same figures from the newer source: the commentary and mapping review still hold
        kept |= {
            k: previous[k]
            for k in ("commentary", "recommended_actions", "mapping_review")
            if k in previous
        }
    case.state = {**pack, **kept}


def correction_reference(case: PodCase, correction_id: str) -> str:
    return f"{case.reference}-{correction_id}"


async def correction_tasks(session: AsyncSession, case: PodCase) -> dict[str, PodPostingTask]:
    tasks = await session.scalars(
        select(PodPostingTask).where(
            PodPostingTask.case_id == case.id, PodPostingTask.kind == TaskKind.JOURNAL_ENTRY
        )
    )
    return {t.reference: t for t in tasks}


async def correction_problems(session: AsyncSession, case: PodCase) -> list[str]:
    """A verified correction must be taken in: the case recalculated on the source that
    proves it, before anyone signs off (or completes) on the old figures."""
    problems = []
    tasks = await correction_tasks(session, case)
    for c in case.state.get("corrections", []):
        if c.get("status") == "withdrawn":
            continue
        task = tasks.get(correction_reference(case, c["id"]))
        if task is None:
            continue
        if task.status == TaskStatus.VERIFIED and task.verification_snapshot_id != case.snapshot_id:
            problems.append(
                f"Correction {c['id']} is verified in a newer source: move the case to that source "
                "(refresh) so the figures are recalculated, then sign off again."
            )
    return problems


async def blockers(c: Ctx) -> list[str]:
    if c.case.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED):
        return []
    state = c.case.state
    problems = list(engine.blocking_issues(state))
    if not state.get("commentary"):
        problems.append(
            "Write the Finance Head commentary first: draft it with AI or write it by hand."
        )
    problems.extend(await correction_problems(c.session, c.case))
    return problems


async def completion_blockers(session: AsyncSession, case: PodCase) -> list[str]:
    return await correction_problems(session, case)


async def stage(session: AsyncSession, case: PodCase) -> str:
    """data -> analysis -> signoff, as the case page's steps."""
    if case.status == CaseStatus.APPROVED:
        return "signoff"
    if engine.blocking_issues(case.state):
        return "data"
    if not case.state.get("commentary"):
        return "analysis"
    return "signoff"


async def phase(session: AsyncSession, case: PodCase, blockers: list[str]) -> str:
    if engine.blocking_issues(case.state):
        return "review"
    if not case.state.get("commentary"):
        return "analysis"
    return "review" if blockers else "ready"


async def summary(session: AsyncSession, case: PodCase) -> str | None:
    """e.g. "2026-04 to 2026-09 · 2026-09 revenue USD 540,000 · margin 15.7%"."""
    metrics = case.state.get("metrics") or []
    if not metrics:
        return None
    last = metrics[-1]
    m = last.get("margin_pct")
    margin = f"{Decimal(m):.1f}%" if m is not None else "undefined"
    return (
        f"{metrics[0]['period']} to {last['period']} · {last['period']} revenue "
        f"{case.state.get('currency', '')} {Decimal(last['revenue']):,.0f} · margin {margin}"
    )


# --- the facts commentary may cite -------------------------------------------------------


def _money(value: Any, currency: str) -> str:
    return f"{currency} {Decimal(str(value)):,.0f}"


def _pct(value: Any) -> str:
    return "undefined (zero baseline)" if value is None else f"{Decimal(str(value)):+.1f}%"


def facts(state: dict[str, Any]) -> list[Fact]:
    """Deterministic, formatted figures (and their IDs) for the commentary to cite."""
    cur = str(state.get("currency", ""))
    out: list[Fact] = []
    for r in state.get("metrics", []):
        p = r["period"]
        m = r.get("margin_pct")
        out += [
            Fact(f"revenue.{p}", f"Revenue {p}", _money(r["revenue"], cur)),
            Fact(
                f"cost_of_services.{p}", f"Cost of services {p}", _money(r["cost_of_services"], cur)
            ),
            Fact(
                f"operating_expense.{p}",
                f"Operating expenses {p}",
                _money(r["operating_expense"], cur),
            ),
            Fact(
                f"operating_profit.{p}", f"Operating profit {p}", _money(r["operating_profit"], cur)
            ),
            Fact(
                f"margin.{p}",
                f"Operating margin {p}",
                "undefined (no revenue)" if m is None else f"{Decimal(m):.1f}%",
            ),
        ]
    change = engine.latest_change(state)
    if change:
        span = f"{change['from']} → {change['to']}"
        out += [
            Fact(
                "change.revenue",
                f"Revenue change {span}",
                f"{_money(change['revenue']['change'], cur)} ({_pct(change['revenue']['pct'])})",
            ),
            Fact(
                "change.cost_of_services",
                f"Cost of services change {span}",
                f"{_money(change['cost_of_services']['change'], cur)} "
                f"({_pct(change['cost_of_services']['pct'])})",
            ),
            Fact(
                "change.operating_expense",
                f"Operating expense change {span}",
                f"{_money(change['operating_expense']['change'], cur)} "
                f"({_pct(change['operating_expense']['pct'])})",
            ),
            Fact(
                "change.total_cost",
                f"Total operating cost change {span}",
                f"{_money(change['total_operating_cost']['change'], cur)} "
                f"({_pct(change['total_operating_cost']['pct'])})",
            ),
            Fact(
                "change.operating_profit",
                f"Operating profit change {span}",
                _money(change["operating_profit"]["change"], cur),
            ),
            Fact(
                "change.margin",
                f"Operating margin shift {span}",
                "undefined"
                if change["margin_pp_exact"] is None
                else f"{Decimal(change['margin_pp_exact']):+.4f} pp exact "
                f"({Decimal(change['margin_pp_displayed']):+.1f} pp between the rounded margins)",
            ),
        ]
        if change.get("outlier"):
            out.append(Fact("change.outlier", "Revenue outlier flag", "revenue moved 10% or more"))
        for i, d in enumerate(change.get("revenue_drivers", []), start=1):
            docs = ", ".join(
                t["document_ref"] or t["id"]
                for t in d["transactions"]
                if t["period"] == change["to"]
            )
            out.append(
                Fact(
                    f"revenue_driver.{i}",
                    f"Revenue contributor {d['counterparty']}",
                    f"{_money(d['change'], cur)}" + (f" ({docs})" if docs else ""),
                )
            )
        for d in change.get("cost_drivers", []):
            vendors = ", ".join(
                f"{v['counterparty']} {_money(v['change'], cur)}"
                for v in d["contributors"][:3]
                if Decimal(str(v["change"])) != 0
            )
            out.append(
                Fact(
                    f"cost_driver.{d['account_id']}",
                    f"{d['account']} change",
                    _money(d["change"], cur) + (f" ({vendors})" if vendors else ""),
                )
            )
    for y in state.get("yoy", []):
        out.append(
            Fact(f"yoy.{y['period']}", f"Revenue vs {y['prior_period']}", _pct(y["revenue_pct"]))
        )
    for i, caveat in enumerate(state.get("caveats", []), start=1):
        out.append(Fact(f"caveat.{i}", "Data caveat", caveat))
    return out


# --- a correction proven by a fresh source --------------------------------------------


def expected_impacts(lines: list[dict[str, Any]], accounts: dict[str, Any]) -> dict[str, Decimal]:
    """P&L account -> how much its reported figure must move (income and costs positive)."""
    impact: dict[str, Decimal] = {}
    for line in lines:
        acct = accounts.get(line["account_id"])
        if acct is None or acct.classification not in PNL:
            continue  # balance sheet side: not in the P&L lines
        debit, credit = Decimal(str(line["debit"])), Decimal(str(line["credit"]))
        move = credit - debit if acct.classification in CREDIT_RAISES else debit - credit
        impact[acct.id] = impact.get(acct.id, Decimal(0)) + move
    return impact


def verify_posting(
    task: PodPostingTask, case: PodCase, original: SnapshotDocument, fresh: SnapshotDocument
) -> list[str]:
    """The fresh source must show the journal's exact account impacts and the GL change they
    cause (TDD: before recalculation and review continue)."""
    correction = next(
        (
            c
            for c in case.state.get("corrections", [])
            if correction_reference(case, c["id"]) == task.reference
        ),
        None,
    )
    if correction is None:
        return []
    accounts = {a.id: a for a in fresh.accounts or []}
    expected = expected_impacts(correction["lines"], accounts)
    period = correction["period"]
    txn = task.external_txn_id or ""
    lines = [
        t
        for t in fresh.transactions or []
        if (t.id == txn or t.id.startswith(f"{txn}:") or t.document_ref == txn)
        and t.status == "Posted"
    ]
    problems = []
    for account_id, move in expected.items():
        posted = sum((t.amount for t in lines if t.account_id == account_id), Decimal(0))
        name = accounts[account_id].name
        if posted != move:
            problems.append(f"{txn} moves {name} by {posted} in the fresh source, not {move}.")

        def gl(doc: SnapshotDocument, account: str = account_id) -> Decimal:
            return sum(
                (
                    g.amount
                    for g in doc.gl_lines or []
                    if (g.account_id, g.period) == (account, period)
                ),
                Decimal(0),
            )

        delta = gl(fresh) - gl(original)
        if delta != move:
            problems.append(
                f"{name} in {period} changed by {delta} between the sources, not by {move}."
            )
    return problems
