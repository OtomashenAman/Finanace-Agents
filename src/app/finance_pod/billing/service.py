"""Billing and invoicing (AR Phase 3): lab submissions, the report-issued event, the
billing analyst's review queue, delivery, the fee schedule, and the measures.

Guardrails:
- agents never change the fee schedule: only an admin's workbook upload does
- a price override takes effect only when the billing analyst approves it, and not by the
  person who proposed it (unless self-approval is allowed, then marked)
- nothing is sent while a flag is open, an override undecided or a line unpriced
"""

import csv
import hmac
import io
import re
import statistics
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.finance_pod.access import FinanceAccess, check_different_person
from src.app.finance_pod.billing import agents, delivery, workbook
from src.app.finance_pod.billing.models import (
    FpContractPrice,
    FpFee,
    FpLabSubmission,
    FpSalesInvoice,
    FpSalesInvoiceLine,
    FpStatement,
    FpSubmissionLine,
    FpTaxRate,
    OverrideStatus,
    SalesInvoiceStatus,
    SubmissionStatus,
)
from src.app.finance_pod.billing.schemas import (
    ContractOut,
    FeeOut,
    FeeScheduleOut,
    ImportResult,
    InvoiceLineOut,
    InvoiceOut,
    InvoiceSummary,
    PerformedIn,
    PublicInvoiceView,
    StatementOut,
    SubmissionIn,
    SubmissionLineOut,
    SubmissionOut,
    TaxOut,
)
from src.app.finance_pod.clients.models import FpClient
from src.app.finance_pod.settings.service import current


class BillingNotFoundError(AppError):
    status_code = 404
    code = "billing_not_found"
    message = "Not found."


class BillingStateError(AppError):
    status_code = 409
    code = "billing_state"


class BillingInvalidError(AppError):
    status_code = 422
    code = "billing_invalid"


class LabKeyError(AppError):
    status_code = 401
    code = "lab_key_invalid"
    message = "Missing or wrong X-Lab-Key."


class InvoiceLinkError(AppError):
    status_code = 404
    code = "invoice_link_invalid"
    message = "This link isn't valid any more. Ask us for a copy of the invoice."


# --- lab submissions and the report-issued event (3.1.1) ------------------------------------


async def _client(session: AsyncSession, code: str) -> FpClient:
    client = await session.scalar(select(FpClient).where(FpClient.code == code.strip()))
    if client is None:
        raise BillingInvalidError(
            f"Client {code} has no account: open one first (Client accounts)."
        )
    return client


async def create_submission(
    session: AsyncSession,
    body: SubmissionIn,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID | None,
    via: str,
) -> FpLabSubmission:
    """A submission received by the lab (the lab system's record). The caller commits."""
    client = await _client(session, body.client_code)
    if body.external_ref and await session.scalar(
        select(FpLabSubmission.id).where(FpLabSubmission.external_ref == body.external_ref)
    ):
        raise BillingStateError(f"Submission {body.external_ref} was already received.")
    row = FpLabSubmission(
        external_ref=body.external_ref,
        client_code=client.code,
        status=SubmissionStatus.IN_LAB,
        turnaround=body.turnaround,
        received_on=body.received_on or utcnow().date(),
        estimate=body.estimate,
        notes=body.notes,
    )
    for i, ln in enumerate(body.lines, 1):
        row.lines.append(
            FpSubmissionLine(
                position=i,
                item_ref=ln.item_ref.strip(),
                stone_type=ln.stone_type.strip().lower(),
                carat=ln.carat,
                service_code=ln.service_code.strip().upper(),
                quantity=ln.quantity,
                requested=True,
                performed=False,
                special_price=ln.special_price,
                special_reason=ln.special_reason,
            )
        )
    session.add(row)
    await session.flush()
    record_event(
        session,
        "fpod.submission_received",
        ctx,
        actor_id=actor_id,
        submission=row.reference,
        client_code=client.code,
        via=via,
        summary=f"Lab received {row.reference} from {client.code} {client.name}: "
        f"{len(row.lines)} service(s), {row.turnaround}"
        + (f", estimate {client.currency} {row.estimate:,.2f}" if row.estimate else "")
        + f" (via {via})",
    )
    return row


async def _submission(
    session: AsyncSession, ref: str | uuid.UUID, *, lock: bool = False
) -> FpLabSubmission:
    if isinstance(ref, uuid.UUID):
        query = select(FpLabSubmission).where(FpLabSubmission.id == ref)
    else:
        match = re.fullmatch(r"SUB-0*(\d+)", ref.strip().upper())
        query = select(FpLabSubmission).where(
            FpLabSubmission.number == int(match.group(1))
            if match
            else FpLabSubmission.external_ref == ref.strip()
        )
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise BillingNotFoundError(f"Submission {ref} not found.")
    return row


async def report_issued(
    session: AsyncSession,
    submission: FpLabSubmission,
    performed: list[PerformedIn] | None,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID | None,
    via: str,
) -> FpSalesInvoice:
    """The report-issued event (3.1.1.a): the billing agent builds the invoice, the fee-rule
    agent prices and checks it; a clean one is delivered at once. The caller commits."""
    if submission.status != SubmissionStatus.IN_LAB:
        raise BillingStateError(f"{submission.reference} is already {submission.status.value}.")
    if performed is None:
        for ln in submission.lines:
            ln.performed = True
    else:
        done = {(p.item_ref.strip(), p.service_code.strip().upper()) for p in performed}
        known = set()
        for ln in submission.lines:
            ln.performed = (ln.item_ref, ln.service_code) in done
            known.add((ln.item_ref, ln.service_code))
        position = len(submission.lines)
        for p in performed:
            key = (p.item_ref.strip(), p.service_code.strip().upper())
            if key in known:
                continue
            known.add(key)
            position += 1
            same_item = next((ln for ln in submission.lines if ln.item_ref == key[0]), None)
            submission.lines.append(
                FpSubmissionLine(
                    position=position,
                    item_ref=key[0],
                    stone_type=(
                        p.stone_type or (same_item.stone_type if same_item else "other")
                    ).lower(),
                    carat=p.carat
                    if p.carat is not None
                    else same_item.carat
                    if same_item
                    else None,
                    service_code=key[1],
                    quantity=p.quantity,
                    requested=False,
                    performed=True,
                )
            )
    if not any(ln.performed for ln in submission.lines):
        raise BillingInvalidError("No service was performed: nothing to invoice.")
    submission.status = SubmissionStatus.REPORT_ISSUED
    submission.report_issued_at, submission.issued_via = utcnow(), via
    await session.flush()
    client = await _client(session, submission.client_code)
    settings = await current(session)
    invoice = await agents.build(session, submission, client, settings.estimate_tolerance_pct)
    session.add(invoice)
    await session.flush()
    items = agents.open_items(invoice)
    record_event(
        session,
        "fpod.sales_invoice_built",
        ctx,
        actor_id=actor_id,
        invoice=invoice.reference,
        submission=submission.reference,
        summary=f"Report issued for {submission.reference} (via {via}); billing agent built "
        f"{invoice.reference} for {client.code} ({invoice.currency} {invoice.total:,.2f}) and "
        "the fee-rule agent "
        + (
            f"flagged {len(items)} item(s) for the billing analyst: {'; '.join(items[:5])}"
            if items
            else "found nothing unusual"
        ),
    )
    if not items:
        invoice.status = SalesInvoiceStatus.APPROVED
        await delivery.deliver(session, invoice, ctx, actor_id=actor_id)
    return invoice


async def issue_report(
    session: AsyncSession,
    access: FinanceAccess,
    submission_id: uuid.UUID,
    performed: list[PerformedIn] | None,
    ctx: RequestContext,
) -> FpSalesInvoice:
    row = await _submission(session, submission_id, lock=True)
    invoice = await report_issued(
        session, row, performed, ctx, actor_id=access.user.id, via="screen"
    )
    await session.commit()
    return invoice


async def lab_event(
    session: AsyncSession,
    key: str | None,
    event: str,
    ref: str,
    received: SubmissionIn | None,
    performed: list[PerformedIn] | None,
    ctx: RequestContext,
) -> dict[str, Any]:
    """An event from the lab system (API), authenticated by the shared lab key."""
    expected = get_settings().lab_events_key
    if expected is None or not key or not hmac.compare_digest(key, expected.get_secret_value()):
        raise LabKeyError
    if event == "submission_received":
        if received is None:
            raise BillingInvalidError("submission_received needs the 'received' submission.")
        received.external_ref = received.external_ref or ref
        row = await create_submission(session, received, ctx, actor_id=None, via="api")
        await session.commit()
        return {"submission": row.reference, "status": row.status.value}
    row = await _submission(session, ref, lock=True)
    invoice = await report_issued(session, row, performed, ctx, actor_id=None, via="api")
    await session.commit()
    return {
        "submission": row.reference,
        "invoice": invoice.reference,
        "status": invoice.status.value,
    }


def _cell(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _rows(data: bytes, filename: str) -> list[dict[str, Any]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        raw = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    else:
        raw = [list(r) for r in csv.reader(io.StringIO(data.decode("utf-8-sig")))]
    if not raw:
        return []
    header = [re.sub(r"[^a-z0-9]", "", _cell(h).lower()) for h in raw[0]]
    return [
        {header[i]: v for i, v in enumerate(r) if i < len(header)} | {"_row": n}
        for n, r in enumerate(raw[1:], start=2)
        if any(_cell(v) for v in r)
    ]


YES = {"yes", "y", "true", "1", "x"}


async def import_submissions(
    session: AsyncSession, access: FinanceAccess, data: bytes, filename: str, ctx: RequestContext
) -> ImportResult:
    """Submissions from the lab system's export, one row per service: Submission, Client,
    Turnaround, Received, Estimate, Item, Stone, Carat, Service, Qty, Special Price, Special
    Reason, Report Issued (yes: build the invoice now), Performed (default yes)."""
    rows = _rows(data, filename)
    if not rows:
        raise BillingInvalidError("The file is empty.")
    need = {"submission", "client", "item", "stone", "service"}
    if missing := need - set(rows[0]):
        raise BillingInvalidError(f"Missing column(s): {', '.join(sorted(missing))}.")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[_cell(r.get("submission"))].append(r)
    errors: list[str] = []
    created = issued = 0

    def dec(v: Any) -> Decimal | None:
        s = _cell(v).replace(",", "")
        return Decimal(s) if s else None

    for ref, items in groups.items():
        first = items[0]
        try:
            body = SubmissionIn(
                client_code=_cell(first.get("client")),
                turnaround=(_cell(first.get("turnaround")) or "standard").lower(),
                received_on=date.fromisoformat(_cell(first.get("received"))[:10])
                if _cell(first.get("received"))
                else None,
                estimate=dec(first.get("estimate")),
                external_ref=ref or None,
                lines=[
                    {
                        "item_ref": _cell(r.get("item")),
                        "stone_type": _cell(r.get("stone")),
                        "carat": dec(r.get("carat")),
                        "service_code": _cell(r.get("service")),
                        "quantity": int(_cell(r.get("qty")) or 1),
                        "special_price": dec(r.get("specialprice")),
                        "special_reason": _cell(r.get("specialreason")) or None,
                    }
                    for r in items
                ],
            )
        except (ValueError, InvalidOperation) as exc:
            errors.append(f"{ref or 'row ' + str(first['_row'])}: {str(exc).splitlines()[0][:200]}")
            continue
        try:
            async with session.begin_nested():
                row = await create_submission(
                    session, body, ctx, actor_id=access.user.id, via="import"
                )
                created += 1
                if _cell(first.get("reportissued")).lower() in YES:
                    performed = [
                        PerformedIn(
                            item_ref=_cell(r.get("item")),
                            service_code=_cell(r.get("service")),
                            quantity=int(_cell(r.get("qty")) or 1),
                        )
                        for r in items
                        if (_cell(r.get("performed")) or "yes").lower() in YES
                    ]
                    await report_issued(
                        session, row, performed, ctx, actor_id=access.user.id, via="import"
                    )
                    issued += 1
        except AppError as exc:
            errors.append(f"{ref}: {exc.message}")
    await session.commit()
    return ImportResult(submissions=created, issued=issued, errors=errors[:50])


async def _names(session: AsyncSession, *ids: uuid.UUID | None) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
    return dict(rows.all())


async def _submission_out(session: AsyncSession, s: FpLabSubmission) -> SubmissionOut:
    inv = await session.scalar(select(FpSalesInvoice).where(FpSalesInvoice.submission_id == s.id))
    name = await session.scalar(select(FpClient.name).where(FpClient.code == s.client_code))
    return SubmissionOut(
        id=s.id,
        reference=s.reference,
        external_ref=s.external_ref,
        client_code=s.client_code,
        client_name=name,
        status=s.status,
        turnaround=s.turnaround,
        received_on=s.received_on,
        estimate=s.estimate,
        notes=s.notes,
        report_issued_at=s.report_issued_at,
        issued_via=s.issued_via,
        lines=[SubmissionLineOut.model_validate(ln, from_attributes=True) for ln in s.lines],
        invoice_id=inv.id if inv else None,
        invoice_reference=inv.reference if inv else None,
        created_at=s.created_at,
    )


async def submissions(
    session: AsyncSession, status: SubmissionStatus | None
) -> list[SubmissionOut]:
    query = select(FpLabSubmission).order_by(FpLabSubmission.number.desc())
    if status:
        query = query.where(FpLabSubmission.status == status)
    return [await _submission_out(session, s) for s in await session.scalars(query)]


async def submission(session: AsyncSession, submission_id: uuid.UUID) -> SubmissionOut:
    return await _submission_out(session, await _submission(session, submission_id))


async def cancel_submission(
    session: AsyncSession,
    access: FinanceAccess,
    submission_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> SubmissionOut:
    row = await _submission(session, submission_id, lock=True)
    if row.status != SubmissionStatus.IN_LAB:
        raise BillingStateError("Only a submission still in the lab can be cancelled.")
    row.status = SubmissionStatus.CANCELLED
    row.notes = ((row.notes or "") + f"\nCancelled: {reason}").strip()
    record_event(
        session,
        "fpod.submission_cancelled",
        ctx,
        actor_id=access.user.id,
        submission=row.reference,
        summary=f"Cancelled {row.reference}: {reason}",
    )
    await session.commit()
    return await _submission_out(session, row)


# --- the billing analyst's review queue (3.3) ---------------------------------------------


async def _invoice(
    session: AsyncSession, invoice_id: uuid.UUID, *, lock: bool = False
) -> FpSalesInvoice:
    inv = await session.get(FpSalesInvoice, invoice_id, with_for_update=lock)
    if inv is None:
        raise BillingNotFoundError("Invoice not found.")
    return inv


async def _summary(session: AsyncSession, inv: FpSalesInvoice) -> dict[str, Any]:
    sub = await session.get(FpLabSubmission, inv.submission_id)
    return {
        "id": inv.id,
        "reference": inv.reference,
        "status": inv.status,
        "client_code": inv.client_code,
        "client_name": inv.client_name,
        "submission_reference": sub.reference if sub else "?",
        "currency": inv.currency,
        "total": inv.total,
        "estimate": inv.estimate,
        "open_items": agents.open_items(inv) if inv.status == SalesInvoiceStatus.REVIEW else [],
        "built_at": inv.built_at,
        "sent_at": inv.sent_at,
    }


async def invoices(
    session: AsyncSession, status: SalesInvoiceStatus | None
) -> list[InvoiceSummary]:
    query = select(FpSalesInvoice).order_by(FpSalesInvoice.number.desc())
    if status:
        query = query.where(FpSalesInvoice.status == status)
    return [InvoiceSummary(**await _summary(session, i)) for i in await session.scalars(query)]


async def invoice(session: AsyncSession, invoice_id: uuid.UUID) -> InvoiceOut:
    inv = await _invoice(session, invoice_id)
    ids = (
        [inv.approved_by]
        + [ln.override_by for ln in inv.lines]
        + [ln.override_decided_by for ln in inv.lines]
    )
    names = await _names(session, *ids)
    sub = await session.get(FpLabSubmission, inv.submission_id)
    return InvoiceOut(
        **await _summary(session, inv),
        version=inv.version,
        submission_id=inv.submission_id,
        client_id=inv.client_id,
        bill_to_email=inv.bill_to_email,
        payment_terms=inv.payment_terms,
        deposit_pct=inv.deposit_pct,
        subtotal=inv.subtotal,
        discount_total=inv.discount_total,
        tax_name=inv.tax_name,
        tax_rate=inv.tax_rate,
        tax=inv.tax,
        flags=inv.flags,
        lines=[
            InvoiceLineOut(
                id=ln.id,
                position=ln.position,
                item_ref=ln.item_ref,
                service_code=ln.service_code,
                description=ln.description,
                stone_type=ln.stone_type,
                carat=ln.carat,
                quantity=ln.quantity,
                list_price=ln.list_price,
                unit_price=ln.unit_price,
                price_source=ln.price_source,
                price_note=ln.price_note,
                amount=ln.amount,
                flags=ln.flags,
                override_price=ln.override_price,
                override_reason=ln.override_reason,
                override_status=ln.override_status,
                override_by_name=names.get(ln.override_by) if ln.override_by else None,
                override_decided_by_name=names.get(ln.override_decided_by)
                if ln.override_decided_by
                else None,
            )
            for ln in inv.lines
        ],
        flagged_on_build=inv.flagged_on_build,
        corrected=inv.corrected,
        approved_by_name=names.get(inv.approved_by) if inv.approved_by else None,
        approved_at=inv.approved_at,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        erp_ref=inv.erp_ref,
        viewed_at=inv.viewed_at,
        void_reason=inv.void_reason,
        report_issued_at=sub.report_issued_at if sub else None,
    )


def _in_review(inv: FpSalesInvoice) -> None:
    if inv.status != SalesInvoiceStatus.REVIEW:
        raise BillingStateError(f"{inv.reference} is {inv.status.value}: nothing to review.")


def _line(inv: FpSalesInvoice, line_id: uuid.UUID) -> FpSalesInvoiceLine:
    line = next((ln for ln in inv.lines if ln.id == line_id), None)
    if line is None:
        raise BillingNotFoundError("Line not found on this invoice.")
    return line


async def propose_override(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    price: Decimal,
    reason: str,
    ctx: RequestContext,
) -> None:
    """A person proposes a different price for a line; the billing analyst approves it."""
    inv = await _invoice(session, invoice_id, lock=True)
    _in_review(inv)
    line = _line(inv, line_id)
    line.override_price, line.override_reason = price, reason.strip()
    line.override_status, line.override_by, line.override_decided_by = (
        OverrideStatus.PENDING,
        access.user.id,
        None,
    )
    record_event(
        session,
        "fpod.price_override_proposed",
        ctx,
        actor_id=access.user.id,
        invoice=inv.reference,
        summary=f"Proposed {inv.currency} {price:,.2f} for {line.item_ref} {line.service_code} on "
        f"{inv.reference} (was {line.unit_price:,.2f}): {reason}",
    )
    await session.commit()


async def decide_override(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    approve: bool,
    note: str,
    ctx: RequestContext,
) -> None:
    """The billing analyst approves or rejects a price override (3.3.1.b). The fee schedule
    is untouched: the override is this line's only."""
    inv = await _invoice(session, invoice_id, lock=True)
    _in_review(inv)
    line = _line(inv, line_id)
    if line.override_status != OverrideStatus.PENDING or line.override_price is None:
        raise BillingStateError("There's no override waiting on that line.")
    self_approval = await check_different_person(
        session,
        access.user,
        line.override_by,
        "Whoever proposed a price override can't also approve it.",
    )
    before = line.unit_price
    line.override_decided_by = access.user.id
    if approve:
        line.override_status = OverrideStatus.APPROVED
        line.price_note = f"override: {line.override_reason}"
        line.flags = _cleared(
            line.flags, "not_on_schedule", access, "Priced by an approved override"
        )
        inv.corrected = True
        agents.totals(inv)
    else:
        line.override_status = OverrideStatus.REJECTED
    record_event(
        session,
        "fpod.price_override_approved" if approve else "fpod.price_override_rejected",
        ctx,
        actor_id=access.user.id,
        invoice=inv.reference,
        self_approval=self_approval,
        summary=f"Billing analyst {'approved' if approve else 'rejected'} the override on "
        f"{line.item_ref} {line.service_code} of {inv.reference}: {inv.currency} "
        f"{line.override_price:,.2f} instead of {before:,.2f}"
        + (f" ({note})" if note.strip() else "")
        + (" (proposed by the same person: self-approval allowed)" if self_approval else ""),
    )
    await session.commit()


def _cleared(
    flags: list[dict[str, Any]], key: str, access: FinanceAccess, note: str
) -> list[dict[str, Any]]:
    """A copy of `flags` with `key` cleared. New dicts, so the JSON column sees the change
    (a dict changed in place compares equal to itself and isn't saved)."""
    stamp = {"by": access.user.full_name, "note": note, "at": utcnow().isoformat()}
    return [
        {**f, "cleared": stamp} if f["key"] == key and not f.get("cleared") else dict(f)
        for f in flags
    ]


async def clear_flag(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID | None,
    key: str,
    note: str,
    ctx: RequestContext,
) -> None:
    inv = await _invoice(session, invoice_id, lock=True)
    _in_review(inv)
    holder: Any = _line(inv, line_id) if line_id else inv
    flag = next((f for f in holder.flags if f["key"] == key and not f.get("cleared")), None)
    if flag is None:
        raise BillingInvalidError("There's no open flag like that.")
    if key == "not_on_schedule":
        raise BillingInvalidError(
            "A line with no published fee is cleared by an approved price override."
        )
    holder.flags = _cleared(holder.flags, key, access, note.strip())
    record_event(
        session,
        "fpod.billing_flag_cleared",
        ctx,
        actor_id=access.user.id,
        invoice=inv.reference,
        flag=key,
        summary=f"Cleared '{flag['label']}' on {inv.reference}"
        + (f" ({holder.item_ref})" if line_id else "")
        + f": {note}",
    )
    await session.commit()


async def approve(
    session: AsyncSession, access: FinanceAccess, invoice_id: uuid.UUID, ctx: RequestContext
) -> None:
    """The analyst releases a reviewed invoice; the delivery agent sends it (3.5)."""
    inv = await _invoice(session, invoice_id, lock=True)
    _in_review(inv)
    items = agents.open_items(inv)
    if items:
        raise BillingInvalidError("Still open: " + "; ".join(items))
    inv.status, inv.approved_by, inv.approved_at = (
        SalesInvoiceStatus.APPROVED,
        access.user.id,
        utcnow(),
    )
    record_event(
        session,
        "fpod.sales_invoice_approved",
        ctx,
        actor_id=access.user.id,
        invoice=inv.reference,
        summary=f"Billing analyst approved {inv.reference} ({inv.currency} {inv.total:,.2f})",
    )
    await delivery.deliver(session, inv, ctx, actor_id=access.user.id)
    await session.commit()


async def void(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> None:
    """Void an invoice before it is sent (e.g. the submission was billed in error)."""
    inv = await _invoice(session, invoice_id, lock=True)
    if inv.status not in (SalesInvoiceStatus.REVIEW, SalesInvoiceStatus.APPROVED):
        raise BillingStateError("A sent invoice is corrected with a credit note, not voided here.")
    inv.status, inv.void_reason = SalesInvoiceStatus.VOID, reason
    record_event(
        session,
        "fpod.sales_invoice_voided",
        ctx,
        actor_id=access.user.id,
        invoice=inv.reference,
        summary=f"Voided {inv.reference}: {reason}",
    )
    await session.commit()


async def invoice_pdf(session: AsyncSession, invoice_id: uuid.UUID) -> tuple[str, bytes]:
    inv = await _invoice(session, invoice_id)
    sub = await session.get(FpLabSubmission, inv.submission_id)
    assert sub is not None  # noqa: S101 - the foreign key holds it
    return f"{inv.reference}.pdf", delivery.invoice_pdf(inv, sub)


# --- the client's view of a sent invoice -----------------------------------------------------


async def _by_token(session: AsyncSession, token: str) -> FpSalesInvoice:
    if not token or len(token) > 100:
        raise InvoiceLinkError
    inv = await session.scalar(
        select(FpSalesInvoice).where(FpSalesInvoice.token_hash == delivery.token_hash(token))
    )
    if inv is None or (inv.token_expires_at and inv.token_expires_at < utcnow()):
        raise InvoiceLinkError
    return inv


async def public_view(session: AsyncSession, token: str) -> PublicInvoiceView:
    inv = await _by_token(session, token)
    if inv.viewed_at is None:
        inv.viewed_at = utcnow()
        await session.commit()
    sub = await session.get(FpLabSubmission, inv.submission_id)
    return PublicInvoiceView(
        organisation=get_settings().email_sender_name,
        reference=inv.reference,
        client_name=inv.client_name,
        client_code=inv.client_code,
        submission_reference=sub.reference if sub else "",
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        payment_terms=inv.payment_terms,
        currency=inv.currency,
        lines=[
            {
                "item_ref": ln.item_ref,
                "description": ln.description,
                "stone_type": ln.stone_type,
                "carat": str(ln.carat) if ln.carat is not None else None,
                "quantity": ln.quantity,
                "unit_price": str(ln.unit_price),
                "amount": str(ln.amount),
            }
            for ln in inv.lines
        ],
        subtotal=inv.subtotal,
        discount_total=inv.discount_total,
        tax_name=inv.tax_name,
        tax_rate=inv.tax_rate,
        tax=inv.tax,
        total=inv.total,
        status="void" if inv.status == SalesInvoiceStatus.VOID else "open",
    )


async def public_pdf(session: AsyncSession, token: str) -> tuple[str, bytes]:
    inv = await _by_token(session, token)
    return await invoice_pdf(session, inv.id)


# --- the fee schedule (only an admin's upload changes it) ----------------------------------


async def fee_schedule(session: AsyncSession) -> FeeScheduleOut:
    fees = await session.scalars(
        select(FpFee).order_by(
            FpFee.service_code, FpFee.stone_type, FpFee.turnaround, FpFee.carat_from
        )
    )
    contracts = await session.scalars(
        select(FpContractPrice).order_by(FpContractPrice.client_code, FpContractPrice.service_code)
    )
    taxes = await session.scalars(select(FpTaxRate).order_by(FpTaxRate.country, FpTaxRate.region))
    return FeeScheduleOut(
        fees=[FeeOut.model_validate(f, from_attributes=True) for f in fees],
        contracts=[ContractOut.model_validate(c, from_attributes=True) for c in contracts],
        taxes=[TaxOut.model_validate(t, from_attributes=True) for t in taxes],
    )


async def upload_fee_schedule(
    session: AsyncSession, access: FinanceAccess, data: bytes, ctx: RequestContext
) -> FeeScheduleOut:
    parsed = workbook.parse(data)
    if parsed.errors:
        raise BillingInvalidError("The fee schedule wasn't loaded: " + " | ".join(parsed.errors))
    before = await session.scalar(select(func.count()).select_from(FpFee)) or 0
    for model in (FpFee, FpContractPrice, FpTaxRate):
        await session.execute(delete(model))
    session.add_all([*parsed.fees, *parsed.contracts, *parsed.taxes])
    record_event(
        session,
        "fpod.fee_schedule_loaded",
        ctx,
        actor_id=access.user.id,
        fees=len(parsed.fees),
        contracts=len(parsed.contracts),
        taxes=len(parsed.taxes),
        summary=f"Loaded the fee schedule: {len(parsed.fees)} fees (was {before}), "
        f"{len(parsed.contracts)} contract prices, {len(parsed.taxes)} tax rates",
    )
    await session.commit()
    return await fee_schedule(session)


# --- statements, measures, overview -----------------------------------------------------------


async def statements(session: AsyncSession) -> list[StatementOut]:
    rows = await session.scalars(
        select(FpStatement).order_by(FpStatement.created_at.desc()).limit(200)
    )
    return [StatementOut.model_validate(r, from_attributes=True) for r in rows]


async def send_statements(
    session: AsyncSession, access: FinanceAccess, ctx: RequestContext
) -> dict[str, Any]:
    result = await delivery.send_statements(session, ctx, actor_id=access.user.id)
    await session.commit()
    return result


async def measures(session: AsyncSession) -> dict[str, Any]:
    """Billing accuracy and days to invoice."""
    sent = list(
        await session.scalars(
            select(FpSalesInvoice).where(FpSalesInvoice.status == SalesInvoiceStatus.SENT)
        )
    )
    days = []
    for inv in sent:
        sub = await session.get(FpLabSubmission, inv.submission_id)
        if sub and sub.report_issued_at and inv.sent_at:
            days.append((inv.sent_at - sub.report_issued_at).total_seconds() / 86400)
    by_status = dict(
        (
            await session.execute(
                select(FpSalesInvoice.status, func.count()).group_by(FpSalesInvoice.status)
            )
        ).all()
    )
    overrides = dict(
        (
            await session.execute(
                select(FpSalesInvoiceLine.override_status, func.count())
                .where(FpSalesInvoiceLine.override_status.is_not(None))
                .group_by(FpSalesInvoiceLine.override_status)
            )
        ).all()
    )
    return {
        "sent": len(sent),
        "accurate": sum(1 for i in sent if not i.corrected),
        "straight_through": sum(1 for i in sent if not i.flagged_on_build),
        "days_to_invoice_median": round(statistics.median(days), 2) if days else None,
        "same_day": sum(1 for d in days if d < 1),
        "in_review": by_status.get(SalesInvoiceStatus.REVIEW, 0),
        "overrides_approved": overrides.get(OverrideStatus.APPROVED, 0),
        "overrides_rejected": overrides.get(OverrideStatus.REJECTED, 0),
        "statements": await session.scalar(select(func.count()).select_from(FpStatement)) or 0,
    }


async def overview_counts(session: AsyncSession) -> tuple[dict[str, int], dict[str, int]]:
    subs = {
        str(s): n
        for s, n in (
            await session.execute(
                select(FpLabSubmission.status, func.count()).group_by(FpLabSubmission.status)
            )
        ).all()
    }
    invs = {
        str(s): n
        for s, n in (
            await session.execute(
                select(FpSalesInvoice.status, func.count()).group_by(FpSalesInvoice.status)
            )
        ).all()
    }
    return subs, invs
