"""The billing agents: the trigger and build (3.1), the fee rules and the check (3.2) and the
delivery (3.5). Pure code on the case's snapshot: every rate comes from the published fee
schedule, the client's own price or a pricing rule, or a billing analyst's override (3.3.1);
the agent never changes the schedule (AR3.G1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select

from src.app.common.clock import utcnow
from src.app.finance_pod.common import cents, doc_of, draft_once, is_sent, need, policy_of, result
from src.app.finance_pod.flows.ar_billing.policy import ArbPolicy
from src.app.finance_pod.flows.ar_billing.results import (
    AccountTerms,
    Delivered,
    EstimateCheck,
    Flags,
    Overrides,
    Performed,
    PerformedLine,
    Priced,
    PricedLine,
    Taxed,
    Triggered,
)
from src.app.service_pod.core.messaging.models import Audience
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import (
    Client,
    PriceRule,
    SnapshotDocument,
    Submission,
    TaxRule,
)
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

Results = dict[str, BaseModel]
INVOICE_MAIL = "client_invoice"


def submission_of(doc: SnapshotDocument, submission_id: str) -> Submission:
    found = next((s for s in doc.submissions or [] if s.id == submission_id), None)
    if found is None:
        raise StepFailedError(f"Submission {submission_id} isn't in the case's snapshot.")
    return found


def client_of(doc: SnapshotDocument, client_id: str) -> Client:
    found = next((c for c in doc.clients or [] if c.id == client_id), None)
    if found is None:
        raise StepFailedError(f"Client {client_id} isn't in the case's snapshot.")
    return found


# --- 3.1 Build the invoice -----------------------------------------------------------------


async def trigger(c: Ctx, step: StepSpec) -> Results:
    """3.1.1: the lab issued the report (GIA's lab system isn't connected: the submission's
    "report issued on" date in the ERP is the event)."""
    sub = submission_of(await doc_of(c), c.case.selection["submission_id"])
    if sub.report_issued_on is None:
        raise StepFailedError("The report isn't issued yet: nothing to bill.")
    return {
        "3.1.1.a": Triggered(submission_id=sub.id, client_id=sub.client_id, submitted_on=sub.date,
                             report_issued_on=sub.report_issued_on)
    }  # fmt: skip


async def build(c: Ctx, step: StepSpec) -> Results:
    """3.1.2: what the lab actually did (lines already billed left out), and the client's
    terms as the books hold them."""
    doc = await doc_of(c)
    sub = submission_of(doc, c.case.selection["submission_id"])
    names = {i.code: i.name for i in doc.items or []}
    lines, billed = [], []
    for ln in sub.lines:
        if ln.billed_amount >= ln.amount and ln.amount > 0:
            billed.append(ln.id)
            continue
        lines.append(
            PerformedLine(submission_line_id=ln.id, item_code=ln.item_code,
                          item_name=names.get(ln.item_code, ln.item_code), qty=ln.qty,
                          lab_rate=ln.rate, added=ln.added)
        )  # fmt: skip
    if not lines:
        raise StepFailedError("Every line of this submission is billed already.")
    client = client_of(doc, sub.client_id)
    open_balance = sum(
        (i.outstanding for i in doc.sales_invoices or []
         if i.client_id == client.id and i.doc_status == "Submitted"),
        Decimal(0),
    )  # fmt: skip
    return {
        "3.1.2.a": Performed(lines=lines, already_billed=billed),
        "3.1.2.b": AccountTerms(
            client_name=client.name, status=client.status, terms_days=client.terms_days,
            deposit_only=client.deposit_only, credit_limit=client.credit_limit,
            open_balance=cents(open_balance), currency=client.currency or doc.currency,
            email=client.email, tax_category=client.tax_category,
        ),
    }  # fmt: skip


# --- 3.2 Price and check -------------------------------------------------------------------


def _rule_applies(rule: PriceRule, client: Client, item_code: str, group: str | None,
                  on: date) -> bool:  # fmt: skip
    if rule.client_id is not None and rule.client_id != client.id:
        return False
    if rule.client_group is not None and rule.client_group != client.group:
        return False
    if rule.item_code is not None and rule.item_code != item_code:
        return False
    if rule.item_group is not None and rule.item_group != group:
        return False
    if rule.valid_from and on < rule.valid_from:
        return False
    return not (rule.valid_upto and on > rule.valid_upto)


def price_line(doc: SnapshotDocument, client: Client, line: PerformedLine, on: date) -> PricedLine:
    """The fee for one line: the client's own price, else the schedule with the most specific
    pricing rule (a contract rate, or a discount); a service without a fee is flagged."""
    prices = doc.selling_prices or []
    schedule = next((p.rate for p in prices if p.item_code == line.item_code
                     and p.client_id is None), None)  # fmt: skip
    own = next((p.rate for p in prices if p.item_code == line.item_code
                and p.client_id == client.id), None)  # fmt: skip
    group = next((i.group for i in doc.items or [] if i.code == line.item_code), None)
    rules = [r for r in doc.price_rules or []
             if _rule_applies(r, client, line.item_code, group, on)]  # fmt: skip
    rules.sort(key=lambda r: (r.client_id is None, r.item_code is None))  # most specific first
    rate, source, discount = schedule, "schedule", None
    if own is not None:
        rate, source = own, "client price"
    elif rules and schedule is not None:
        rule = rules[0]
        if rule.rate is not None:
            rate, source = rule.rate, "contract discount"
        elif rule.discount_pct:
            discount = rule.discount_pct
            rate, source = schedule * (100 - discount) / 100, "contract discount"
    if rate is None:
        return PricedLine(submission_line_id=line.submission_line_id, item_code=line.item_code,
                          qty=line.qty, schedule_rate=None, rate=Decimal(0), source="no fee",
                          discount_pct=None, amount=Decimal(0))  # fmt: skip
    rate = cents(rate)
    return PricedLine(
        submission_line_id=line.submission_line_id, item_code=line.item_code, qty=line.qty,
        schedule_rate=schedule, rate=rate, source=source,
        discount_pct=discount, amount=cents(rate * line.qty),
    )  # fmt: skip


def tax_rule_for(doc: SnapshotDocument, category: str | None) -> TaxRule | None:
    """Tax by the client's location (AR3.R3): the template of its tax category, else the
    default one."""
    rules = doc.tax_rules or []
    return next((t for t in rules if category and t.tax_category == category), None) or next(
        (t for t in rules if t.default), None
    )


async def apply_rules(c: Ctx, step: StepSpec) -> Results:
    """3.2.1: fees, discounts and contract prices; then currency and tax."""
    doc = await doc_of(c)
    performed = need(c, "3.1.2.a", Performed)
    terms = need(c, "3.1.2.b", AccountTerms)
    sub = submission_of(doc, c.case.selection["submission_id"])
    client = client_of(doc, sub.client_id)
    on = utcnow().date()
    lines = [price_line(doc, client, ln, on) for ln in performed.lines]
    net = cents(sum((ln.amount for ln in lines), Decimal(0)))
    rule = tax_rule_for(doc, terms.tax_category)
    rate = rule.rate_pct if rule else Decimal(0)
    tax = cents(net * rate / 100)
    return {
        "3.2.1.a": Priced(lines=lines, net_total=net),
        "3.2.1.b": Taxed(currency=terms.currency, tax_rule=rule.id if rule else None,
                         tax_category=terms.tax_category, rate_pct=rate, tax=tax,
                         total=cents(net + tax)),
    }  # fmt: skip


async def check(c: Ctx, step: StepSpec) -> Results:
    """3.2.2: the invoice against the fee estimate the client saw, and anything unusual."""
    doc = await doc_of(c)
    policy = policy_of(c.case, ArbPolicy)
    sub = submission_of(doc, c.case.selection["submission_id"])
    priced = need(c, "3.2.1.a", Priced)
    performed = need(c, "3.1.2.a", Performed)
    terms = need(c, "3.1.2.b", AccountTerms)
    estimate = sub.fee_estimate
    diff = pct = None
    within = True
    if estimate is not None:
        diff = cents(priced.net_total - estimate)
        pct = cents(diff * 100 / estimate) if estimate else None
        within = pct is not None and abs(pct) <= policy.estimate_tolerance_pct
    flags: list[str] = []
    # Above the estimate is what the client didn't expect; below it is explained by the
    # client's own price or a contract discount, else it's flagged too (lost revenue)
    explained = any(ln.source in ("client price", "contract discount") for ln in priced.lines)
    if not within and estimate is not None and (diff is None or diff > 0 or not explained):
        flags.append(f"{priced.net_total:,.2f} is {pct}% off the fee estimate of {estimate:,.2f}")
    for ln, done in zip(priced.lines, performed.lines, strict=True):
        if done.added:
            flags.append(f"{ln.item_code} was added in the lab after the client submitted")
        if ln.source == "no fee":
            flags.append(f"{ln.item_code} has no published fee")
        if ln.qty > policy.unusual_qty:
            flags.append(f"{ln.item_code}: {ln.qty} units is unusual for one submission")
    if terms.status != "Active":
        flags.append(f"{terms.client_name} is {terms.status}: confirm before invoicing")
    if not terms.email:
        flags.append(f"{terms.client_name} has no contact email for the invoice")
    return {
        "3.2.2.a": EstimateCheck(fee_estimate=estimate, net_total=priced.net_total,
                                 difference=diff, difference_pct=pct, within_tolerance=within,
                                 tolerance_pct=policy.estimate_tolerance_pct),
        "3.2.2.b": Flags(flags=flags),
    }  # fmt: skip


async def no_flags(c: Ctx) -> str | None:
    """3.3.1 applies only when the check flagged something."""
    found = result(c, "3.2.2.b", Flags)
    if found is not None and not found.flags:
        return "Nothing flagged: the invoice follows the schedule and the estimate"
    return None


def final_lines(c: Ctx) -> list[PricedLine]:
    """The priced lines with the billing analyst's overrides (this invoice only)."""
    priced = need(c, "3.2.1.a", Priced)
    overrides = result(c, "3.3.1.b", Overrides)
    by_item = {o.item_code: o for o in overrides.overrides} if overrides else {}
    out = []
    for ln in priced.lines:
        o = by_item.get(ln.item_code)
        if o is None:
            out.append(ln)
            continue
        out.append(ln.model_copy(update={"rate": cents(o.rate),
                                         "amount": cents(o.rate * ln.qty)}))  # fmt: skip
    return out


# --- 3.5 Deliver ---------------------------------------------------------------------------


async def invoice_task(c: Ctx) -> PodPostingTask | None:
    return await c.session.scalar(
        select(PodPostingTask).where(
            PodPostingTask.case_id == c.case.id,
            PodPostingTask.kind == TaskKind.CREATE_SALES_INVOICE,
            PodPostingTask.status != TaskStatus.CANCELLED,
        )
    )


async def send(c: Ctx, step: StepSpec) -> Results:
    """3.5.1: the invoice is posted (verified by a fresh snapshot), then emailed to the
    client's contact; it goes on the client's monthly statement."""
    task = await invoice_task(c)
    if task is None:
        raise StepFailedError("The invoice isn't queued for the ERP yet (it is on release).")
    if task.status != TaskStatus.VERIFIED or task.verification_snapshot_id is None:
        where = f" as {task.external_txn_id}" if task.external_txn_id else ""
        raise StepFailedError(
            f"The invoice is {task.status.value.replace('_', ' ')}{where}: post it if needed, "
            "then verify it with a fresh snapshot and run this step again."
        )
    snapshot = await c.session.get(PodSnapshot, task.verification_snapshot_id)
    assert snapshot is not None  # noqa: S101 - verification keeps the snapshot
    posted = next(
        (i for i in snapshots.document(snapshot).sales_invoices or []
         if i.id == task.external_txn_id),
        None,
    )  # fmt: skip
    if posted is None:
        raise StepFailedError("The verifying snapshot doesn't hold the invoice.")
    terms = need(c, "3.1.2.b", AccountTerms)
    if not terms.email:
        raise StepFailedError(f"{terms.client_name} has no contact email in the ERP: add one.")
    lines = "\n".join(f"- {ln.item_code} x {ln.qty:g} @ {ln.rate:,.2f} = {ln.amount:,.2f}"
                      for ln in final_lines(c))  # fmt: skip
    due = f", due {posted.due_date:%d %b %Y}" if posted.due_date else ""
    message = await draft_once(
        c, purpose=INVOICE_MAIL, audience=Audience.CUSTOMER, to_email=terms.email,
        to_name=terms.client_name, subject=f"Invoice {posted.id}",
        body=(f"Hello,\n\nPlease find invoice {posted.id} for submission "
              f"{c.case.selection['submission_id']}:\n\n{lines}\n\nNet {posted.net_total:,.2f}, "
              f"tax {posted.tax_total:,.2f}, total {posted.currency} {posted.total:,.2f}{due}."
              "\n\nThank you."),
    )  # fmt: skip
    if not is_sent(message):
        raise StepFailedError(
            f"Invoice {posted.id} is in the ERP and its email to {terms.email} is drafted: "
            "review and send it, then run this step again."
        )
    return {
        "3.5.1.a": Delivered(
            erp_invoice=posted.id,
            total=posted.total,
            message_id=message.id,
            portal="no client portal for invoices yet: sent by email",
        ),
    }
