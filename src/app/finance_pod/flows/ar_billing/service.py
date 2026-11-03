"""Billing's own rules: opening a case per billable submission, the billing analyst's
overrides, the sales invoice it posts to the ERP once released, the monthly statements, and
the rules and measures."""

from __future__ import annotations

import contextlib
import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.common import cents, doc_of, need, policy_values, result
from src.app.finance_pod.flows.ar_billing import agents
from src.app.finance_pod.flows.ar_billing.policy import ArbPolicy
from src.app.finance_pod.flows.ar_billing.results import (
    AccountTerms,
    Delivered,
    Overrides,
    Priced,
    Taxed,
    Triggered,
)
from src.app.service_pod.core.cases.exceptions import CaseActionError, CaseSelectionError
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.messaging.models import MessageStatus, PodMessage
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument, Submission
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.steps.models import PodCaseStep
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec, StepStatus
from src.app.service_pod.core.tasks import service as tasks
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus
from src.app.service_pod.core.tasks.schemas import TaskCreate
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

KEY = WorkflowKey.AR_BILLING
STATEMENT = "client_statement"


def billable(sub: Submission) -> bool:
    """The report is issued and something of it isn't billed yet."""
    return (
        sub.doc_status == "Submitted"
        and sub.report_issued_on is not None
        and any(ln.billed_amount < ln.amount for ln in sub.lines)
    )


async def live_cases(session: AsyncSession) -> set[str]:
    return set(
        await session.scalars(
            select(PodCase.selection["submission_id"].astext).where(
                PodCase.workflow == KEY, PodCase.status != CaseStatus.CANCELLED
            )
        )
    )


def to_bill(doc: SnapshotDocument, taken: set[str]) -> list[Submission]:
    """AR3.R1: every completed (report issued) submission not billed and without a case."""
    return [s for s in doc.submissions or [] if billable(s) and s.id not in taken]


async def on_create(
    session: AsyncSession, case: PodCase, doc: SnapshotDocument, refresh: bool
) -> None:
    sub_id = case.selection.get("submission_id")
    sub = next((s for s in doc.submissions or [] if s.id == sub_id), None)
    if sub is None:
        raise CaseSelectionError(f"Submission {sub_id} isn't in this snapshot.")
    unknown = set(case.selection) - {"submission_id"}
    if unknown:
        raise CaseSelectionError(f"Unknown selection: {', '.join(sorted(unknown))}.")
    if refresh:
        return
    if not billable(sub):
        why = "its report isn't issued yet" if sub.report_issued_on is None else "it's billed"
        raise CaseSelectionError(f"{sub_id} can't be billed: {why}.")
    if sub_id in await live_cases(session):
        raise CaseSelectionError(f"{sub_id} already has a billing case.")
    version, values = await policy_values(session, KEY.value, ArbPolicy)
    case.state = {
        **case.state,
        "policy": {"version": version, "values": values.model_dump(mode="json")},
    }


# --- 3.3.1 the billing analyst's overrides ---------------------------------------------------


async def after_review(c: Ctx, step: StepSpec) -> str | None:
    """3.3.1: an override names an item of this invoice, and changes only this invoice
    (AR3.G1: the fee schedule stays as it is)."""
    overrides = need(c, "3.3.1.b", Overrides)
    priced = need(c, "3.2.1.a", Priced)
    items = {ln.item_code for ln in priced.lines}
    unknown = [o.item_code for o in overrides.overrides if o.item_code not in items]
    if unknown:
        raise CaseActionError(f"Not on this invoice: {', '.join(unknown)}.")
    if overrides.overrides:
        c.case.state = {**c.case.state, "_overridden": True}
        changed = ", ".join(f"{o.item_code} at {o.rate:,.2f}" for o in overrides.overrides)
        return f"price overrides on this invoice only: {changed}"
    return None


# --- after the release: the sales invoice in the ERP ----------------------------------------


async def create_invoice(c: Ctx) -> None:
    """Released (checked, and reviewed when flagged): queue the sales invoice from the
    submission's lines at the final rates, with the client's tax, and post it."""
    if c.request is None:
        return
    doc = await doc_of(c)
    trig = need(c, "3.1.1.a", Triggered)
    taxed = need(c, "3.2.1.b", Taxed)
    rule = next((t for t in doc.tax_rules or [] if t.id == taxed.tax_rule), None)
    invoice: dict[str, Any] = {
        "customer": trig.client_id,
        "company": doc.company_name,
        "currency": taxed.currency,
        "ignore_pricing_rule": 1,  # the rates are the ones this case set
        "items": [
            {"item_code": ln.item_code, "qty": str(ln.qty), "rate": str(ln.rate),
             "sales_order": trig.submission_id, "so_detail": ln.submission_line_id}
            for ln in agents.final_lines(c)
        ],
    }  # fmt: skip
    if rule is not None:
        invoice["taxes_and_charges"] = rule.id
        invoice["taxes"] = [
            {"charge_type": "On Net Total", "account_head": rule.account_id,
             "rate": str(rule.rate_pct), "description": rule.id}
        ]  # fmt: skip
    task = await tasks.add_task(
        c.session, c.case,
        TaskCreate(kind=TaskKind.CREATE_SALES_INVOICE,
                   reference=f"{trig.client_id} {trig.submission_id}",
                   instructions={"doc": invoice}),
        c.user.id,
    )  # fmt: skip
    with contextlib.suppress(tasks.TaskRefusedError):
        await tasks.post_now(c.session, c.access, task, c.case, c.request)


# --- 3.5.1.b monthly statements ------------------------------------------------------------


async def statement_sent(c: Ctx, step: StepSpec) -> Any:
    """3.5.1.b: the invoice is on a statement the client was sent (a billing analyst sends
    the month's statements in one batch)."""
    from src.app.finance_pod.flows.ar_billing.results import OnStatement

    delivered = need(c, "3.5.1.a", Delivered)
    terms = need(c, "3.1.2.b", AccountTerms)
    sent = await c.session.scalar(
        select(PodMessage)
        .where(
            PodMessage.purpose == STATEMENT,
            PodMessage.status == MessageStatus.SENT,
            PodMessage.to_email == terms.email,
            PodMessage.body.contains(delivered.erp_invoice),
        )
        .order_by(PodMessage.created_at.desc())
    )
    if sent is None:
        raise StepFailedError(
            f"{delivered.erp_invoice} isn't on a statement sent to {terms.client_name} yet: "
            "draft and send the month's statements (Finance POD dashboard), then run again."
        )
    month = str((sent.subject or "").rsplit(" ", 1)[-1])
    return {"3.5.1.b": OnStatement(statement_month=month,
                                   how=f"sent with the {month} statement batch")}  # fmt: skip


def statement_body(doc: SnapshotDocument, client_id: str, month: str, today: date) -> str:
    """The client's open items as the books hold them today."""
    rows = sorted(
        (i for i in doc.sales_invoices or []
         if i.client_id == client_id and i.doc_status == "Submitted" and i.outstanding > 0),
        key=lambda i: i.posting_date,
    )  # fmt: skip
    lines = []
    for i in rows:
        late = (today - i.due_date).days if i.due_date and i.due_date < today else 0
        due = f"due {i.due_date:%d %b %Y}" if i.due_date else "no due date"
        overdue = f"  ({late} days overdue)" if late else ""
        lines.append(f"- {i.id}  {i.posting_date:%d %b %Y}  {due}  {i.currency} "
                     f"{i.outstanding:,.2f}{overdue}")  # fmt: skip
    total = cents(sum((i.outstanding for i in rows), Decimal(0)))
    return ("Hello,\n\nYour statement of account for " + month + ", as of "
            f"{today:%d %b %Y}:\n\n" + "\n".join(lines) + f"\n\nBalance due: {total:,.2f}"
            "\n\nThank you.")  # fmt: skip


async def newest_doc(session: AsyncSession, case: PodCase) -> SnapshotDocument:
    """The newest snapshot of the case's entity that holds the AR collections."""
    rows = await session.scalars(
        select(PodSnapshot)
        .where(PodSnapshot.entity_id == case.entity_id)
        .order_by(PodSnapshot.created_at.desc())
        .limit(20)
    )
    for snap in rows:
        doc = snapshots.document(snap)
        if doc.sales_invoices is not None:
            return doc
    return snapshots.document(await session.get_one(PodSnapshot, case.snapshot_id))


async def waiting_for_statement(session: AsyncSession) -> dict[str, list[PodCase]]:
    """Released billing cases whose invoice is sent and not yet on a statement, by client."""
    cases = list(
        await session.scalars(
            select(PodCase).where(PodCase.workflow == KEY, PodCase.status == CaseStatus.APPROVED)
        )
    )
    if not cases:
        return {}
    rows = await session.scalars(
        select(PodCaseStep).where(
            PodCaseStep.case_id.in_([c.id for c in cases]),
            PodCaseStep.l5_code.in_(["3.5.1.a", "3.5.1.b", "3.1.1.a"]),
        )
    )
    by_case: dict[Any, dict[str, PodCaseStep]] = defaultdict(dict)
    for r in rows:
        by_case[r.case_id][r.l5_code] = r
    out: dict[str, list[PodCase]] = defaultdict(list)
    for c in cases:
        steps = by_case[c.id]
        if (
            steps["3.5.1.a"].status == StepStatus.DONE
            and steps["3.5.1.b"].status != StepStatus.DONE
        ):
            out[str(steps["3.1.1.a"].result["client_id"])].append(c)  # type: ignore[index]
    return out


# --- rules and measures --------------------------------------------------------------------


async def schedule_rule(c: Ctx) -> str | None:
    """AR3.R2 Fees per published schedule or contract: every line is priced from the schedule,
    a client's price or a pricing rule, or overridden by a billing analyst."""
    priced = result(c, "3.2.1.a", Priced)
    if priced is None:
        return None
    overridden = result(c, "3.3.1.b", Overrides)
    by_override = {o.item_code for o in overridden.overrides} if overridden else set()
    unpriced = [ln.item_code for ln in priced.lines
                if ln.source == "no fee" and ln.item_code not in by_override]  # fmt: skip
    if unpriced:
        return (f"No published fee for {', '.join(unpriced)}: a billing analyst sets it on this "
                "invoice (AR3.R2).")  # fmt: skip
    return None


async def accuracy(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AR3.M1 Billing accuracy (%): released invoices that needed no price override."""
    done = [c for c in cases if c.status in (CaseStatus.APPROVED, CaseStatus.COMPLETED)]
    if not done:
        return None
    clean = sum(1 for c in done if not c.state.get("_overridden"))
    return cents(Decimal(clean * 100) / len(done))


async def days_to_invoice(session: AsyncSession, cases: list[PodCase]) -> Decimal | None:
    """AR3.M2 Days to invoice (median): report issued -> invoice verified in the ERP."""
    if not cases:
        return None
    issued = {}
    for row in await session.scalars(
        select(PodCaseStep).where(
            PodCaseStep.case_id.in_([c.id for c in cases]), PodCaseStep.l5_code == "3.1.1.a"
        )
    ):
        if row.result:
            issued[row.case_id] = date.fromisoformat(row.result["report_issued_on"])
    rows = await session.execute(
        select(PodPostingTask.case_id, PodPostingTask.verified_at).where(
            PodPostingTask.case_id.in_([c.id for c in cases]),
            PodPostingTask.kind == TaskKind.CREATE_SALES_INVOICE,
            PodPostingTask.status == TaskStatus.VERIFIED,
        )
    )
    days = [(at.date() - issued[cid]).days for cid, at in rows.all() if at and cid in issued]
    return Decimal(str(round(statistics.median(days), 1))) if days else None


def today() -> date:
    return utcnow().date()
