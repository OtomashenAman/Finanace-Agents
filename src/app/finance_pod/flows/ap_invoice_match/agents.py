"""The invoice's agents: posting (3.2), matching (3.4), exceptions (3.5) and receipts (3.6).
Every figure comes from the snapshot; the agents never change a PO (AP3.G1) and never post
an invoice (it goes on to coding and approval, AP-4)."""

from __future__ import annotations

import difflib
import re
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select

from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.common import cents, doc_of, draft_once, need, policy_of, result
from src.app.finance_pod.flows.ap_invoice_match.policy import ApmPolicy
from src.app.finance_pod.flows.ap_invoice_match.results import (
    BuyerDecision,
    DuplicateDecision,
    DuplicateSearch,
    ExceptionView,
    InvoiceRecord,
    LineByLine,
    LineMatch,
    LoopClosed,
    Nudge,
    OpenException,
    PossibleDuplicate,
    ReceiptConfirmed,
    SendToCoding,
    SourceDocument,
    Tolerances,
    VendorQuery,
)
from src.app.finance_pod.models import FinanceCapacityAssignment
from src.app.service_pod.core.cases.models import PodReviewTask, ReviewTaskKind
from src.app.service_pod.core.messaging.models import ArtifactKind, Audience, PodArtifact
from src.app.service_pod.core.snapshots.contract import Bill, SnapshotDocument
from src.app.service_pod.core.steps.spec import StepFailedError, StepSpec, StepStatus
from src.app.service_pod.core.tasks.models import PodPostingTask, TaskKind, TaskStatus

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.service import Ctx

Results = dict[str, BaseModel]
VARIANCES = ("price", "quantity")


def bill_of(c: Ctx, doc: SnapshotDocument) -> Bill:
    bill_id = c.case.selection["bill_id"]
    bill = next((b for b in doc.bills or [] if b.id == bill_id), None)
    if bill is None:
        raise StepFailedError(f"Invoice {bill_id} isn't in the case's snapshot.")
    return bill


def _policy(c: Ctx) -> ApmPolicy:
    return policy_of(c.case, ApmPolicy)


# --- 3.2.1 Create invoice in ERP ----------------------------------------------------------


async def validate_invoice(c: Ctx, step: StepSpec) -> Results:
    """The invoice as ERPNext holds it (a draft from intake), checked, with the vendor's own
    document attached as its source."""
    doc = await doc_of(c)
    bill = bill_of(c, doc)
    vendor = next((v for v in doc.vendors or [] if v.id == bill.vendor_id), None)
    problems: list[str] = []
    if bill.doc_status != "Draft":
        problems.append(f"{bill.id} is {bill.doc_status.lower()} already, not an incoming invoice")
    if vendor is None:
        problems.append(f"vendor {bill.vendor_id} isn't in the vendor master")
    elif vendor.status != "Active":
        problems.append(f"{vendor.name} is {vendor.status}")
    if not bill.bill_number:
        problems.append("the vendor's invoice number is missing")
    if not bill.lines:
        problems.append("the invoice has no lines")
    source = await c.session.scalar(
        select(PodArtifact)
        .where(PodArtifact.case_id == c.case.id, PodArtifact.kind == ArtifactKind.INVOICE_COPY)
        .order_by(PodArtifact.created_at.desc())
    )
    if source is None:
        problems.append("attach the vendor's invoice document (Documents, kind: invoice copy)")
    if problems:
        raise StepFailedError("Can't take the invoice yet: " + "; ".join(problems) + ".")
    assert source is not None  # noqa: S101 - checked above
    return {
        "3.2.1.a": InvoiceRecord(
            erp_invoice=bill.id, vendor_id=bill.vendor_id, bill_number=bill.bill_number or "",
            bill_date=bill.bill_date, total=bill.total, lines=len(bill.lines),
            po_backed=all(ln.order_line_id for ln in bill.lines),
            checks=["vendor active", "invoice number", "lines", "source document"],
        ),
        "3.2.1.b": SourceDocument(document_id=source.id, filename=source.filename,
                                  sha256=source.sha256),
    }  # fmt: skip


# --- 3.2.2 Duplicate guard -----------------------------------------------------------------


def _number(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


async def duplicate_guard(c: Ctx, step: StepSpec) -> Results:
    """AP3.R2: the same vendor, a near-identical number and the same amount is a duplicate
    (whatever its status): blocked with the reason, for a person to confirm or clear."""
    doc = await doc_of(c)
    bill = bill_of(c, doc)
    policy = _policy(c)
    others = [b for b in doc.bills or [] if b.id != bill.id and b.vendor_id == bill.vendor_id
              and b.return_against is None and b.doc_status != "Cancelled"]  # fmt: skip
    matches = []
    for other in others:
        similarity = difflib.SequenceMatcher(
            None, _number(bill.bill_number), _number(other.bill_number)
        ).ratio()
        if similarity >= policy.duplicate_number_similarity and abs(other.total - bill.total) <= (
            policy.amount_tolerance
        ):
            matches.append(
                PossibleDuplicate(bill_id=other.id, bill_number=other.bill_number,
                                  total=other.total, doc_status=other.doc_status,
                                  number_similarity=round(similarity, 3))
            )  # fmt: skip
    if matches:
        first = matches[0]
        explanation = (
            f"Looks like {first.bill_id} ({first.bill_number}, {first.total}, "
            f"{first.doc_status.lower()}): same vendor, invoice number "
            f"{first.number_similarity:.0%} alike, same amount. Reject it as a duplicate, or "
            "clear the review task with the evidence that it's a different invoice."
        )
        if not any(t.subject == "Possible duplicate" for t in c.children.review_tasks):
            task = PodReviewTask(
                case_id=c.case.id, kind=ReviewTaskKind.OTHER, subject="Possible duplicate",
                detail=explanation, blocking=True, created_by=None,
            )  # fmt: skip
            c.session.add(task)
            c.children.review_tasks.append(task)
    else:
        explanation = f"No other invoice of {bill.vendor_id} with this number and amount."
    return {
        "3.2.2.a": DuplicateSearch(compared=len(others), matches=matches),
        "3.2.2.b": DuplicateDecision(blocked=bool(matches), explanation=explanation),
    }


# --- 3.4 Match -------------------------------------------------------------------------------


def match_lines(doc: SnapshotDocument, bill: Bill, policy: ApmPolicy) -> list[LineMatch]:
    """Each invoice line against its PO line and the accepted receipts (AP3.R1: tolerances
    apply per line)."""
    order_lines = {ln.id: (po, ln) for po in doc.purchase_orders or [] for ln in po.lines}
    out: list[LineMatch] = []
    for bl in bill.lines:
        found = order_lines.get(bl.order_line_id or "")
        if found is None:
            out.append(
                LineMatch(item_code=bl.item_code, order_id=bl.order_id,
                          order_line_id=bl.order_line_id, billed_qty=bl.qty, billed_rate=bl.rate,
                          po_qty=None, po_rate=None,
                          received_qty=None, billed_before=Decimal(0), price_variance_pct=None,
                          quantity_over=Decimal(0), status="no_po",
                          reason="Not on a PO (or its PO isn't in the snapshot): goes to coding")
            )  # fmt: skip
            continue
        po, pl = found
        received = sum(
            (r.qty for rc in doc.purchase_receipts or [] if rc.doc_status == "Submitted"
             for r in rc.lines if r.order_line_id == pl.id),
            Decimal(0),
        )  # fmt: skip
        billed_before = sum(
            (x.qty for b in doc.bills or [] if b.id != bill.id and b.doc_status == "Submitted"
             and b.return_against is None for x in b.lines if x.order_line_id == pl.id),
            Decimal(0),
        )  # fmt: skip
        variance = cents((bl.rate - pl.rate) / pl.rate * 100) if pl.rate else None
        over = max(bl.qty + billed_before - received, Decimal(0))
        price_off = (
            variance is not None
            and abs(variance) > policy.price_tolerance_pct
            and abs(bl.rate - pl.rate) * bl.qty > policy.amount_tolerance
        )
        reasons = []
        if received == 0:
            reasons.append("nothing received against this PO line yet")
        elif over > policy.quantity_tolerance:
            reasons.append(f"billed {over.normalize()} more than received")
        if price_off:
            reasons.append(
                f"price {variance:+}% vs the PO ({bl.rate.normalize()} vs {pl.rate.normalize()})"
            )
        status = ("no_receipt" if received == 0 else
                  "quantity" if over > policy.quantity_tolerance else
                  "price" if price_off else "match")  # fmt: skip
        out.append(
            LineMatch(item_code=bl.item_code, order_id=po.id, order_line_id=pl.id,
                      billed_qty=bl.qty, billed_rate=bl.rate, po_qty=pl.qty, po_rate=pl.rate,
                      received_qty=received, billed_before=billed_before,
                      price_variance_pct=variance, quantity_over=over, status=status,
                      reason="; ".join(reasons) or "within tolerance")
        )  # fmt: skip
    return out


async def three_way_match(c: Ctx, step: StepSpec) -> Results:
    # A blocked duplicate goes no further: matching it would route it to coding (AP3.R2)
    from src.app.finance_pod.flows.ap_invoice_match.service import duplicate_rule

    blocked = await duplicate_rule(c)
    if blocked:
        raise StepFailedError(
            f"{blocked} Reject it (cancel the case), or resolve the review task with the "
            "evidence that it's a different invoice, then run this step again."
        )
    doc = await doc_of(c)
    policy = _policy(c)
    version = c.case.state.get("policy", {}).get("version", "")
    return {
        "3.4.1.a": LineByLine(lines=match_lines(doc, bill_of(c, doc), policy)),
        "3.4.1.b": Tolerances(price_pct=policy.price_tolerance_pct,
                              quantity=policy.quantity_tolerance, amount=policy.amount_tolerance,
                              policy_version=version),
    }  # fmt: skip


def _route(lines: list[LineMatch]) -> str:
    if all(ln.status == "match" for ln in lines):
        return "coding"
    if all(ln.status in ("match", "no_po") for ln in lines):
        return "coding_non_po"
    return "exception"


async def classify(c: Ctx, step: StepSpec) -> Results:
    lines = need(c, "3.4.1.a", LineByLine).lines
    route = _route(lines)
    if "_first_outcome" not in c.case.state:  # first-pass match rate (AP3.M1)
        c.case.state = {**c.case.state, "_first_outcome": route}
    variances = [
        f"{ln.item_code}: {ln.reason}" for ln in lines if ln.status not in ("match", "no_po")
    ]
    reason = {
        "coding": "every line matches its PO and receipt within tolerance",
        "coding_non_po": "no PO to match: coded and approved as a non-PO invoice (AP-4)",
        "exception": f"{len(variances)} line(s) don't match",
    }[route]
    return {
        "3.4.2.a": SendToCoding(sent=route != "exception", route=route, reason=reason),
        "3.4.2.b": OpenException(opened=route == "exception", variances=variances),
    }


def _lines(c: Ctx) -> list[LineMatch]:
    found = result(c, "3.4.1.a", LineByLine)
    return found.lines if found else []


async def no_variance(c: Ctx) -> str | None:
    """3.5.1 / 3.5.2 apply to price and quantity variances only."""
    if result(c, "3.4.2.a", SendToCoding) is None:
        return None
    if not any(ln.status in VARIANCES for ln in _lines(c)):
        return "No price or quantity variance to resolve"
    return None


async def no_exception(c: Ctx) -> str | None:
    routed = result(c, "3.4.2.a", SendToCoding)
    if routed is not None and routed.route != "exception":
        return "The invoice matched: nothing to re-match"
    return None


async def receipts_complete(c: Ctx) -> str | None:
    if result(c, "3.4.2.a", SendToCoding) is None:
        return None
    if not any(ln.status in ("no_receipt", "quantity") for ln in _lines(c)):
        return "Every line is received"
    return None


# --- 3.5 Resolve variances ------------------------------------------------------------------


async def prepare_exception(c: Ctx, step: StepSpec) -> Results:
    doc = await doc_of(c)
    bill = bill_of(c, doc)
    lines = _lines(c)
    rows = [
        {"item": ln.item_code, "po": ln.order_id, "po_qty": str(ln.po_qty),
         "po_rate": str(ln.po_rate), "received": str(ln.received_qty),
         "billed_qty": str(ln.billed_qty),
         "billed_rate": str(ln.billed_rate), "status": ln.status, "reason": ln.reason}
        for ln in lines
    ]  # fmt: skip
    vendor = next((v for v in doc.vendors or [] if v.id == bill.vendor_id), None)
    message = None
    if vendor and vendor.email:
        issues = "\n".join(
            f"- {ln.item_code}: {ln.reason}" for ln in lines if ln.status in VARIANCES
        )
        message = await draft_once(
            c, purpose="invoice_query", audience=Audience.VENDOR, to_email=vendor.email,
            to_name=vendor.name, subject=f"Your invoice {bill.bill_number}: a question",
            body=(f"Dear {vendor.name},\n\nYour invoice {bill.bill_number} doesn't match our "
                  f"purchase order:\n\n{issues}\n\nPlease send a corrected invoice or a credit "
                  "note, or explain the difference, by replying to this email.\n\nThank you."),
        )  # fmt: skip
    return {
        "3.5.1.a": ExceptionView(rows=rows),
        "3.5.1.b": VendorQuery(message_id=message.id if message else None,
                               to_email=vendor.email if vendor else None),
    }  # fmt: skip


async def close_loop(c: Ctx, step: StepSpec) -> Results:
    """Re-match on the case's current snapshot (after a receipt, a credit or a PO change) and
    release the invoice once nothing is left out of tolerance."""
    doc = await doc_of(c)
    bill = bill_of(c, doc)
    receipts = list(
        await c.session.scalars(
            select(PodPostingTask).where(
                PodPostingTask.case_id == c.case.id,
                PodPostingTask.kind == TaskKind.CREATE_PURCHASE_RECEIPT,
                PodPostingTask.status != TaskStatus.CANCELLED,
            )
        )
    )
    if any(t.status != TaskStatus.VERIFIED for t in receipts):
        raise StepFailedError(
            "The receipt is posted to ERPNext: verify it with a fresh snapshot and move the case "
            "to that snapshot, then run this step again."
        )
    lines = match_lines(doc, bill, _policy(c))
    decision = result(c, "3.5.2.a", BuyerDecision)
    if any(ln.status == "no_receipt" for ln in lines):
        raise StepFailedError("Some lines still have no receipt (3.6).")
    open_variances = [ln for ln in lines if ln.status in VARIANCES]
    how = "every line matches now"
    if open_variances:
        if decision is None:
            raise StepFailedError("A variance remains and the buyer hasn't decided (3.5.2).")
        if decision.decision == "accept":
            how = f"variance accepted by the buyer: {decision.note}"
        elif decision.decision == "credit":
            credit = sum(
                (-b.total for b in doc.bills or []
                 if b.return_against == bill.id and b.doc_status == "Submitted"),
                Decimal(0),
            )  # fmt: skip
            assert decision.expected_credit is not None  # noqa: S101 - the model requires it
            if credit < decision.expected_credit:
                raise StepFailedError(
                    f"Waiting for the vendor's credit note ({decision.expected_credit} expected, "
                    f"{credit} in the snapshot): move the case to a snapshot that holds it."
                )
            how = f"credit note of {credit} against {bill.id}"
        else:
            raise StepFailedError(
                "The PO isn't amended yet in this snapshot: the buyer changes it in ERPNext (the "
                "agent never does, AP3.G1); then move the case to a fresh snapshot."
            )
    snapshot_ref = c.case.snapshot_sha[:12]
    return {"3.5.3.a": LoopClosed(rematched_on=snapshot_ref, lines=lines, released=True, how=how)}


# --- 3.6 Chase missing receipts -------------------------------------------------------------


async def nudge_receiver(c: Ctx, step: StepSpec) -> Results:
    """Ask the receivers: the request is their step 3.6.2 in their queue."""
    waiting = [f"{ln.item_code} ({ln.order_id})" for ln in _lines(c)
               if ln.status in ("no_receipt", "quantity")]  # fmt: skip
    rows = await c.session.execute(
        select(User.full_name)
        .join(FinanceCapacityAssignment, FinanceCapacityAssignment.user_id == User.id)
        .where(
            FinanceCapacityAssignment.capacity == Cap.RECEIVER,
            (FinanceCapacityAssignment.entity_id == c.case.entity_id)
            | FinanceCapacityAssignment.entity_id.is_(None),
            User.is_active.is_(True),
        )
    )
    receivers = sorted({r[0] for r in rows.all()})
    if not receivers:
        admins = await c.session.scalars(
            select(User.full_name).where(User.role == UserRole.FINANCE_ADMIN, User.is_active)
        )
        receivers = [f"{n} (Finance Admin: nobody holds the receiver capacity)" for n in admins]
    return {"3.6.1.a": Nudge(lines=waiting, receivers=receivers)}


def receipt_doc(
    c: Ctx, doc: SnapshotDocument, bill: Bill, confirmed: ReceiptConfirmed
) -> dict[str, object]:
    """The ERPNext Purchase Receipt a receiver's confirmation becomes."""
    order_lines = {ln.id: (po, ln) for po in doc.purchase_orders or [] for ln in po.lines}
    items = []
    for rl in confirmed.lines:
        if rl.received_qty <= 0:
            continue
        po, pl = order_lines[rl.order_line_id]
        items.append(
            {"item_code": rl.item_code, "qty": str(rl.received_qty), "rate": str(pl.rate),
             "purchase_order": po.id, "purchase_order_item": pl.id,
             "cost_center": pl.cost_centre_id, "lab": pl.lab_id, "project": pl.grant_id}
        )  # fmt: skip
    receipt: dict[str, object] = {
        "supplier": bill.vendor_id, "company": doc.company_name, "items": items,
    }  # fmt: skip
    # ERPNext refuses a date in the future of its own time zone: a receipt from today or
    # yesterday takes ERPNext's today; an earlier one keeps the date the receiver gave
    if confirmed.received_on < utcnow().date() - timedelta(days=1):
        receipt |= {"posting_date": confirmed.received_on.isoformat(), "set_posting_time": 1}
    return receipt


def step_done(c: Ctx, key: str) -> bool:
    return any(r.step_key == key and r.status == StepStatus.DONE for r in c.children.steps)
