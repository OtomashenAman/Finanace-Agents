"""The close agent (L4 6.1): accruals, the subledger-to-ledger reconciliation and the vendor
statements. Pure code on the snapshot: it proposes, the controller posts (AP6.G1)."""

from __future__ import annotations

import calendar
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select

from src.app.common.text_extraction.base import ExtractionError
from src.app.common.text_extraction.registry import extract_text
from src.app.finance_pod.common import cents, doc_of, need, policy_of
from src.app.finance_pod.flows.ap_month_close.policy import ApcPolicy
from src.app.finance_pod.flows.ap_month_close.results import (
    AccrualProposal,
    Comparison,
    Difference,
    Explanation,
    JournalLine,
    ReceiptsNotInvoiced,
    StatementCheck,
    StatementGap,
    StatementRead,
    SubledgerVsLedger,
    UnbilledLine,
)
from src.app.service_pod.core.cases.models import CaseStatus, PodCase
from src.app.service_pod.core.messaging.models import ArtifactKind, PodArtifact
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.snapshots.importers.erpnext import LAB_FIELD
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec
from src.app.service_pod.core.workflows import WorkflowKey

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

Results = dict[str, BaseModel]
SUBLEDGER_VOUCHERS = {"Purchase Invoice", "Payment Entry"}
ZERO = Decimal(0)


def period_end(period: str) -> date:
    year, month = int(period[:4]), int(period[5:7])
    return date(year, month, calendar.monthrange(year, month)[1])


def _policy(c: Ctx) -> ApcPolicy:
    return policy_of(c.case, ApcPolicy)


# --- 6.1.1 Accruals --------------------------------------------------------------------------


def unbilled(doc: SnapshotDocument, until: date) -> list[UnbilledLine]:
    """PO lines received (submitted receipts up to `until`) beyond what posted invoices
    billed by then."""
    items = {i.code: i for i in doc.items or []}
    received: dict[str, Decimal] = defaultdict(Decimal)
    for rc in doc.purchase_receipts or []:
        if rc.doc_status == "Submitted" and rc.date <= until:
            for rl in rc.lines:
                if rl.order_line_id:
                    received[rl.order_line_id] += rl.qty
    billed: dict[str, Decimal] = defaultdict(Decimal)
    for b in doc.bills or []:
        if b.doc_status == "Submitted" and b.posting_date <= until:
            for bl in b.lines:
                if bl.order_line_id:
                    billed[bl.order_line_id] += bl.qty
    out = []
    for po in doc.purchase_orders or []:
        for ln in po.lines:
            gap = received[ln.id] - billed[ln.id]
            if gap <= 0:
                continue
            item = items.get(ln.item_code)
            out.append(
                UnbilledLine(
                    order_id=po.id, order_line_id=ln.id, vendor_id=po.vendor_id,
                    item_code=ln.item_code, stock_item=bool(item and item.stock_item),
                    received_qty=received[ln.id], billed_qty=billed[ln.id], unbilled_qty=gap,
                    rate=ln.rate, value=cents(gap * ln.rate), account_id=ln.account_id,
                    cost_centre_id=ln.cost_centre_id, lab_id=ln.lab_id, grant_id=ln.grant_id,
                )
            )  # fmt: skip
    return out


def accrued_account(doc: SnapshotDocument) -> str | None:
    return next((b.account_id for b in doc.ledger_balances or [] if b.kind == "accrued"), None)


async def accruals(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    end = period_end(c.case.selection["period"])
    lines = unbilled(doc, end)
    stock = cents(sum((ln.value for ln in lines if ln.stock_item), ZERO))
    non_stock = [ln for ln in lines if not ln.stock_item]
    total = cents(sum((ln.value for ln in non_stock), ZERO))
    note = (
        f"Stock items received and not billed ({stock}) are already in Stock Received But Not "
        "Billed: not journalled again."
    )
    journal: list[JournalLine] = []
    if non_stock:
        credit_to = accrued_account(doc)
        if credit_to is None:
            raise StepFailedError("The source has no accrued-expenses account to credit.")
        by_coding: dict[tuple[str | None, ...], Decimal] = defaultdict(Decimal)
        for ln in non_stock:
            if ln.account_id is None:
                raise StepFailedError(f"{ln.order_id} {ln.item_code} has no expense account.")
            by_coding[(ln.account_id, ln.cost_centre_id, ln.lab_id, ln.grant_id)] += ln.value
        journal = [
            JournalLine(account_id=str(k[0]), debit=cents(v), credit=ZERO, cost_centre_id=k[1],
                        lab_id=k[2], grant_id=k[3])
            for k, v in by_coding.items()
        ] + [JournalLine(account_id=credit_to, debit=ZERO, credit=total)]  # fmt: skip
        note += f" Services and non-stock items ({total}) are accrued, reversed on the 1st."
    return {
        "6.1.1.a": ReceiptsNotInvoiced(
            period_end=end, lines=lines, stock_total=stock, non_stock_total=total
        ),
        "6.1.1.b": AccrualProposal(
            posting_date=end if journal else None,
            reversal_date=end + timedelta(days=1) if journal else None,
            lines=journal, total=total, note=note,
        ),
    }  # fmt: skip


# --- 6.1.2 Reconcile --------------------------------------------------------------------------


def reconcile(doc: SnapshotDocument) -> tuple[SubledgerVsLedger, list[Difference], Decimal]:
    """Subledger vs ledger at the snapshot's date, and the postings that explain the gaps."""
    balances = {b.kind: b for b in doc.ledger_balances or []}
    if "payable" not in balances:
        raise StepFailedError("The source doesn't give the payables (Creditors) balance.")
    open_bills = cents(sum(
        (b.outstanding for b in doc.bills or []
         if b.doc_status == "Submitted" and b.posting_date <= doc.as_of),
        ZERO,
    ))  # fmt: skip
    payable = balances["payable"]
    comparisons = [
        Comparison(ledger="payable", account_id=payable.account_id, subledger=open_bills,
                   ledger_balance=payable.balance, difference=cents(payable.balance - open_bills))
    ]  # fmt: skip
    rnb = balances.get("received_not_billed")
    stock = cents(sum((ln.value for ln in unbilled(doc, doc.as_of) if ln.stock_item), ZERO))
    if rnb is not None:
        comparisons.append(
            Comparison(ledger="received_not_billed", account_id=rnb.account_id, subledger=stock,
                       ledger_balance=rnb.balance, difference=cents(rnb.balance - stock))
        )  # fmt: skip
    items: list[Difference] = []
    for e in doc.ledger_entries or []:
        if e.kind == "payable" and e.voucher_type not in SUBLEDGER_VOUCHERS:
            who = f" for {e.party}" if e.party else ""
            items.append(
                Difference(
                    ledger="payable", amount=e.amount, voucher=f"{e.voucher_type} {e.voucher_id}",
                    explanation=f"posted to the supplier account{who} without an invoice: it "
                    "changes the ledger, not any invoice's balance",
                )
            )  # fmt: skip
    explained = sum((d.amount for d in items), ZERO)
    unexplained = cents(sum((x.difference for x in comparisons), ZERO) - explained)
    return SubledgerVsLedger(as_of=doc.as_of, comparisons=comparisons), items, unexplained


async def reconcile_step(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    comparison, items, unexplained = reconcile(doc)
    held = list(
        await c.session.scalars(
            select(PodCase).where(
                PodCase.workflow == WorkflowKey.AP_INVOICE_MATCH,
                PodCase.entity_id == c.case.entity_id,
                PodCase.status == CaseStatus.DRAFT,
            )
        )
    )
    held_refs = [p.reference for p in held if p.state.get("_first_outcome") == "exception"]
    if abs(unexplained) <= _policy(c).tolerance:
        unexplained = ZERO
    return {
        "6.1.2.a": comparison,
        "6.1.2.b": Explanation(items=items, unexplained=unexplained, held_invoices=held_refs),
    }


# --- 6.1.3 Vendor statements -----------------------------------------------------------------

_AMOUNT = re.compile(r"(-?\d{1,3}(?:,\d{3})+\.\d{2}|-?\d+\.\d{2})\s*$")
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9\-/]*")
_BALANCE = re.compile(r"(?i)\b(?:closing|balance|amount due|total due)\b")


def _norm(ref: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", ref.upper())


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def read_statement(text: str, doc: SnapshotDocument, document_id: uuid.UUID) -> StatementRead:
    """The vendor named in the statement, its lines (a reference and an amount each) and its
    closing balance, against that vendor's open invoices in the books."""
    vendors = sorted(doc.vendors or [], key=lambda v: -len(v.name))
    vendor = next((v for v in vendors if v.name.lower() in text.lower()), None)
    open_bills = {
        _norm(b.bill_number or b.id): b
        for b in doc.bills or []
        if vendor is not None and b.vendor_id == vendor.id and b.doc_status == "Submitted"
        and b.outstanding != 0
    }  # fmt: skip
    entries: dict[str, Decimal] = {}
    shown: dict[str, str] = {}  # normalised -> as the statement writes it
    closing = None
    for raw in (line.strip() for line in text.splitlines()):
        amount = _AMOUNT.search(raw)
        if amount is None:
            continue
        if _BALANCE.search(raw):
            closing = _money(amount.group(1))
            continue
        tokens = _TOKEN.findall(raw.upper()[: amount.start()])
        refs = [t for t in tokens if re.search(r"\d", t) and re.search(r"[A-Z]", t)]
        ref = next((t for t in refs if _norm(t) in open_bills), refs[0] if refs else None)
        if ref is not None:
            entries[_norm(ref)] = _money(amount.group(1))
            shown[_norm(ref)] = ref
    gaps: list[StatementGap] = []
    books_balance = None
    if vendor is not None:
        books_balance = cents(sum((b.outstanding for b in open_bills.values()), ZERO))
        for ref, stated in entries.items():
            bill = open_bills.get(ref)
            if bill is None:
                gaps.append(StatementGap(reference=shown[ref], kind="not_in_books",
                                         statement_amount=stated, books_amount=None))  # fmt: skip
            elif bill.outstanding != stated:
                gaps.append(StatementGap(reference=bill.bill_number or bill.id,
                                         kind="amount_differs", statement_amount=stated,
                                         books_amount=bill.outstanding))  # fmt: skip
        for ref, bill in open_bills.items():
            if ref not in entries:
                gaps.append(StatementGap(reference=bill.bill_number or bill.id,
                                         kind="not_on_statement", statement_amount=None,
                                         books_amount=bill.outstanding))  # fmt: skip
    return StatementRead(
        document_id=document_id, vendor_id=vendor.id if vendor else None,
        closing_balance=closing, books_balance=books_balance, lines_read=len(entries),
        gaps=gaps,
    )  # fmt: skip


async def statements(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    uploaded = list(
        await c.session.scalars(
            select(PodArtifact).where(
                PodArtifact.case_id == c.case.id, PodArtifact.kind == ArtifactKind.VENDOR_STATEMENT
            )
        )
    )
    reads = []
    for artifact in uploaded:
        content = await c.session.scalar(
            select(PodArtifact.content).where(PodArtifact.id == artifact.id)
        )
        try:
            text = extract_text(content or b"", artifact.filename).text
        except ExtractionError:
            text = ""
        reads.append(read_statement(text, doc, artifact.id))
    balances: dict[str, Decimal] = defaultdict(Decimal)
    for b in doc.bills or []:
        if b.doc_status == "Submitted":
            balances[b.vendor_id] += b.outstanding
    have = {r.vendor_id for r in reads}
    key = sorted(v for v, bal in balances.items() if bal >= _policy(c).statement_min_balance)
    missing = [v for v in key if v not in have]
    return {
        "6.1.3.a": StatementCheck(
            statements=reads, missing=missing,
            gaps=sum(len(r.gaps) for r in reads) + len(missing),
        )
    }  # fmt: skip


def accrual_journal(c: Ctx, doc: SnapshotDocument, reverse: bool) -> dict[str, object] | None:
    """The ERPNext Journal Entry of the proposed accrual (or its reversal on the 1st)."""
    proposal = need(c, "6.1.1.b", AccrualProposal)
    if not proposal.lines or proposal.posting_date is None or proposal.reversal_date is None:
        return None
    period = c.case.selection["period"]
    rows = []
    for ln in proposal.lines:
        debit, credit = (ln.credit, ln.debit) if reverse else (ln.debit, ln.credit)
        row = {"account": ln.account_id, "debit_in_account_currency": str(debit),
               "credit_in_account_currency": str(credit), "cost_center": ln.cost_centre_id,
               LAB_FIELD: ln.lab_id, "project": ln.grant_id}  # fmt: skip
        rows.append({k: v for k, v in row.items() if v is not None})
    when = proposal.reversal_date if reverse else proposal.posting_date
    return {
        "voucher_type": "Journal Entry", "company": doc.company_name,
        "posting_date": when.isoformat(),
        "user_remark": f"{'Reversal of the ' if reverse else ''}AP accrual {period}: received, "
                       f"not invoiced ({c.case.reference})",
        "accounts": rows,
    }  # fmt: skip
