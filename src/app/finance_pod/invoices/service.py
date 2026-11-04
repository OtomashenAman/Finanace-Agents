"""AP Phase 3: invoice processing and matching.

3.1 capture (assumed by the slide's "validated data"): the capture agent reads the invoice;
    AP confirms the data
3.2 posting agent: the duplicate guard blocks and explains; otherwise the invoice is created
    in the ERP with its source document
3.4 match agent: line by line against the PO and receipts, GIA tolerances; a match goes to
    coding, a variance opens an exception
3.5 exception agent prepares the case and drafts the vendor query; the buyer decides
    (accept, credit note, amend PO, reject); the agent re-matches and releases
3.6 receipt agent asks the receiver (a single-use mobile link); their confirmation re-runs
    the match

Guardrails: agents never change a PO price (only the buyer's "amend PO" decision does, and
each change is recorded with its old and new value); every decision is in the audit trail;
a variance can't be accepted while what's billed hasn't been received.
"""

import hashlib
import secrets
import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.finance_pod import mail
from src.app.finance_pod.access import FinanceAccess
from src.app.finance_pod.erp import ErpInvoice, get_erp
from src.app.finance_pod.invoices import agents
from src.app.finance_pod.invoices.models import (
    ExceptionDecision,
    ExceptionStatus,
    FpInvoice,
    FpInvoiceException,
    FpInvoiceLine,
    FpPoAmendment,
    FpReceipt,
    FpReceiptLine,
    FpReceiptRequest,
    InvoiceStatus,
    ReceiptRequestStatus,
)
from src.app.finance_pod.invoices.schemas import (
    DecisionIn,
    ExceptionOut,
    InvoiceIn,
    InvoiceLineOut,
    InvoiceOut,
    InvoiceSummary,
    ReceiptIn,
    ReceiptOut,
    ReceiptPortalView,
    ReceiptRequestOut,
)
from src.app.finance_pod.orders.models import FpPurchaseOrder, PoStatus
from src.app.finance_pod.reference.models import FpVendor, VendorStatus
from src.app.finance_pod.requests.models import FpPurchaseRequest
from src.app.finance_pod.settings.service import current as current_settings
from src.app.service_pod.common import ai

DOC_TYPES = {"application/pdf", "image/png", "image/jpeg", "text/plain"}
LIVE = (InvoiceStatus.POSTED, InvoiceStatus.EXCEPTION, InvoiceStatus.READY)
RECEIPT_ISSUES = frozenset({"no_receipt", "quantity"})
RECEIPT_LINK_DAYS = 14


class InvoiceNotFoundError(AppError):
    status_code = 404
    code = "invoice_not_found"
    message = "Invoice not found."


class InvoiceStateError(AppError):
    status_code = 409
    code = "invoice_state"


class InvoiceInvalidError(AppError):
    status_code = 422
    code = "invoice_invalid"


class ReceiptLinkError(AppError):
    status_code = 404
    code = "receipt_link_invalid"
    message = "This link isn't valid any more."


# --- reading -------------------------------------------------------------------------------


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
    return dict(rows.all())


def _summary(inv: FpInvoice, po_ref: str | None) -> dict[str, Any]:
    return {
        "id": inv.id,
        "reference": inv.reference,
        "status": inv.status,
        "vendor_code": inv.vendor_code,
        "vendor_name": inv.vendor_name,
        "vendor_invoice_number": inv.vendor_invoice_number,
        "invoice_date": inv.invoice_date,
        "total": inv.total,
        "currency": inv.currency,
        "po_reference": po_ref or inv.po_reference,
        "first_pass_matched": inv.first_pass_matched,
        "created_at": inv.created_at,
    }


async def _po_refs(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(FpPurchaseOrder.id, FpPurchaseOrder.number).where(FpPurchaseOrder.id.in_(ids))
    )
    return {i: f"PO-{n:05d}" for i, n in rows.all()}


async def list_invoices(
    session: AsyncSession, status: InvoiceStatus | None, po_id: uuid.UUID | None = None
) -> list[InvoiceSummary]:
    query = select(FpInvoice).order_by(FpInvoice.number.desc())
    if status is not None:
        query = query.where(FpInvoice.status == status)
    if po_id is not None:
        query = query.where(FpInvoice.po_id == po_id)
    invoices = list(await session.scalars(query))
    refs = await _po_refs(session, {i.po_id for i in invoices if i.po_id})
    return [InvoiceSummary(**_summary(i, refs.get(i.po_id) if i.po_id else None)) for i in invoices]


async def _load(session: AsyncSession, invoice_id: uuid.UUID, *, lock: bool = False) -> FpInvoice:
    inv = await session.get(FpInvoice, invoice_id, with_for_update=lock)
    if inv is None:
        raise InvoiceNotFoundError
    return inv


def _age(exc: FpInvoiceException) -> float:
    end = exc.resolved_at or utcnow()
    return round((end - exc.created_at).total_seconds() / 86400, 1)


async def _exception_out(
    session: AsyncSession, exc: FpInvoiceException, inv: FpInvoice | None = None
) -> ExceptionOut:
    inv = inv or await session.get(FpInvoice, exc.invoice_id)
    assert inv is not None  # noqa: S101 - cascade
    names = await _names(session, {exc.decided_by})
    refs = await _po_refs(session, {inv.po_id} if inv.po_id else set())
    return ExceptionOut(
        id=exc.id,
        invoice_id=inv.id,
        invoice_reference=inv.reference,
        vendor_name=inv.vendor_name,
        po_reference=refs.get(inv.po_id) if inv.po_id else None,
        status=exc.status,
        kinds=exc.kinds,
        issues=exc.issues,
        vendor_query_subject=exc.vendor_query_subject,
        vendor_query_body=exc.vendor_query_body,
        decision=exc.decision,
        decided_by_name=names.get(exc.decided_by) if exc.decided_by else None,
        decided_at=exc.decided_at,
        note=exc.note,
        credit_expected=exc.credit_expected,
        credit_received=exc.credit_received,
        credit_note_ref=exc.credit_note_ref,
        created_at=exc.created_at,
        resolved_at=exc.resolved_at,
        age_days=_age(exc),
        total=inv.total,
        currency=inv.currency,
    )


async def _current_exception(session: AsyncSession, inv: FpInvoice) -> FpInvoiceException | None:
    return await session.scalar(
        select(FpInvoiceException)
        .where(FpInvoiceException.invoice_id == inv.id)
        .order_by(FpInvoiceException.created_at.desc())
        .limit(1)
    )


def request_out(r: FpReceiptRequest, token: str | None = None) -> ReceiptRequestOut:
    return ReceiptRequestOut(
        id=r.id,
        po_id=r.po_id,
        receiver_email=r.receiver_email,
        receiver_name=r.receiver_name,
        status=r.status,
        nudges=r.nudges,
        last_nudged_at=r.last_nudged_at,
        confirmed_at=r.confirmed_at,
        expires_at=r.expires_at,
        link=receipt_url(token) if token else None,
    )


async def detail(
    session: AsyncSession, invoice_id: uuid.UUID, link_token: str | None = None
) -> InvoiceOut:
    inv = await _load(session, invoice_id)
    names = await _names(session, {inv.validated_by})
    refs = await _po_refs(session, {inv.po_id} if inv.po_id else set())
    exc = await _current_exception(session, inv)
    requests = list(
        await session.scalars(
            select(FpReceiptRequest)
            .where(FpReceiptRequest.invoice_id == inv.id)
            .order_by(FpReceiptRequest.created_at)
        )
    )
    return InvoiceOut(
        **_summary(inv, refs.get(inv.po_id) if inv.po_id else None),
        version=inv.version,
        due_date=inv.due_date,
        tax_code=inv.tax_code,
        tax_total=inv.tax_total,
        po_id=inv.po_id,
        filename=inv.filename,
        extraction=inv.extraction,
        validated_by_name=names.get(inv.validated_by) if inv.validated_by else None,
        validated_at=inv.validated_at,
        duplicate=inv.duplicate,
        erp_system=inv.erp_system,
        erp_ref=inv.erp_ref,
        posted_at=inv.posted_at,
        # Matches stored before the quantity trail existed get it from their lines
        match=(
            {**inv.match, "trail": agents.quantity_trail(inv.match)}
            if inv.match and "trail" not in inv.match
            else inv.match
        ),
        match_runs=inv.match_runs,
        released_at=inv.released_at,
        paid_at=inv.paid_at,
        payment_ref=inv.payment_ref,
        rejected_reason=inv.rejected_reason,
        lines=[
            InvoiceLineOut(
                position=ln.position,
                description=ln.description,
                quantity=ln.quantity,
                unit_price=ln.unit_price,
                amount=ln.amount,
                po_line=ln.po_line,
            )
            for ln in inv.lines
        ],
        lines_total=inv.lines_total,
        exception=await _exception_out(session, exc, inv) if exc else None,
        receipt_requests=[
            request_out(r, link_token if i == len(requests) - 1 else None)
            for i, r in enumerate(requests)
        ],
        can_edit=inv.status in (InvoiceStatus.CAPTURED, InvoiceStatus.DUPLICATE),
    )


async def file(session: AsyncSession, invoice_id: uuid.UUID) -> tuple[str, str, bytes]:
    inv = await _load(session, invoice_id)
    content = await session.scalar(select(FpInvoice.content).where(FpInvoice.id == inv.id))
    if not content or not inv.filename:
        raise InvoiceNotFoundError("This invoice has no document.")
    return inv.filename, inv.content_type or "application/octet-stream", content


# --- 3.1 capture -----------------------------------------------------------------------------


async def _resolve_po(
    session: AsyncSession, ref: str | None, vendor: str | None
) -> FpPurchaseOrder | None:
    n = agents.po_number_key(ref)
    if n is None:
        return None
    po = await session.scalar(select(FpPurchaseOrder).where(FpPurchaseOrder.number == n))
    if po is None or (vendor and po.vendor_code != vendor):
        return None
    return po


def _apply(inv: FpInvoice, body: InvoiceIn) -> None:
    inv.vendor_code = body.vendor_code
    inv.vendor_invoice_number = (body.vendor_invoice_number or "").strip() or None
    inv.invoice_date, inv.due_date = body.invoice_date, body.due_date
    inv.currency, inv.tax_code = body.currency, body.tax_code
    inv.tax_total, inv.total = body.tax_total, body.total
    inv.po_reference = (body.po_reference or "").strip() or None
    inv.lines = [
        FpInvoiceLine(
            position=n,
            description=ln.description.strip(),
            quantity=ln.quantity,
            unit_price=ln.unit_price,
            po_line=ln.po_line,
        )
        for n, ln in enumerate(body.lines, start=1)
    ]


async def capture(
    session: AsyncSession,
    access: FinanceAccess,
    filename: str,
    content_type: str,
    data: bytes,
    llm: LLMProvider,
    ctx: RequestContext,
) -> FpInvoice:
    """Keep the document and let the capture agent read it. A reading that doesn't hold up
    is noted; AP types the data instead."""
    content_type = content_type.split(";")[0].strip().lower()
    if content_type not in DOC_TYPES:
        raise InvoiceInvalidError("Upload the invoice as a PDF, PNG, JPEG or TXT.")
    if not data:
        raise InvoiceInvalidError("The file is empty.")
    sha = hashlib.sha256(data).hexdigest()
    same = await session.scalar(select(FpInvoice).where(FpInvoice.sha256 == sha))
    settings = await current_settings(session)
    inv = FpInvoice(
        status=InvoiceStatus.CAPTURED,
        currency=settings.currency,
        tax_total=0,
        filename=filename[:255],
        content_type=content_type,
        sha256=sha,
        content=data,
        created_by=access.user.id,
        lines=[],
    )
    try:
        read = await agents.capture(llm, data, filename)
    except (LLMError, ai.AiOutputRejectedError) as exc:
        reason = exc.message if isinstance(exc, ai.AiOutputRejectedError) else "AI unavailable"
        inv.extraction = {"error": reason}
    else:
        inv.extraction = read
        vendors = list(
            await session.scalars(
                select(FpVendor).where(FpVendor.status == VendorStatus.APPROVED, FpVendor.active)
            )
        )
        vendor = agents.find_vendor(vendors, read.get("vendor_name"), read.get("vendor_tax_id"))
        inv.vendor_code = vendor.code if vendor else None
        inv.vendor_name = vendor.name if vendor else read.get("vendor_name")
        inv.vendor_invoice_number = read.get("invoice_number")
        inv.invoice_date = agents.iso_date(read.get("invoice_date"))
        inv.due_date = agents.iso_date(read.get("due_date"))
        currency = str(read.get("currency") or "").upper()
        inv.currency = currency if len(currency) == 3 else inv.currency
        inv.tax_total = agents.number(read.get("tax_total")) or Decimal("0")
        inv.total = agents.number(read.get("total"))
        inv.po_reference = read.get("po_number")
        po = await _resolve_po(session, inv.po_reference, inv.vendor_code)
        inv.po_id = po.id if po else None
        lines = []
        for n, ln in enumerate(read.get("lines") or [], start=1):
            qty, price = agents.number(ln.get("quantity")), agents.number(ln.get("unit_price"))
            if qty and qty > 0 and price is not None:
                lines.append(
                    FpInvoiceLine(
                        position=n,
                        description=str(ln.get("description"))[:500],
                        quantity=qty,
                        unit_price=price,
                    )
                )
        inv.lines = lines
    session.add(inv)
    await session.flush()
    record_event(
        session,
        "fpod.invoice_captured",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        invoice_id=str(inv.id),
        summary=f"Capture agent read {inv.reference} ({filename[:80]})"
        + (
            f": {inv.vendor_name or 'vendor ?'}, invoice {inv.vendor_invoice_number or '?'}, "
            f"total {inv.total if inv.total is not None else '?'}"
            if "error" not in (inv.extraction or {})
            else f"; couldn't read it ({inv.extraction['error']})"
        )
        + (f". The same file was uploaded before as {same.reference}" if same else ""),
    )
    await session.commit()
    return inv


async def create_manual(
    session: AsyncSession, access: FinanceAccess, body: InvoiceIn, ctx: RequestContext
) -> FpInvoice:
    inv = FpInvoice(
        status=InvoiceStatus.CAPTURED,
        currency=body.currency,
        tax_total=0,
        created_by=access.user.id,
        lines=[],
    )
    _apply(inv, body)
    await _fill_vendor_po(session, inv)
    session.add(inv)
    await session.flush()
    record_event(
        session,
        "fpod.invoice_captured",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        invoice_id=str(inv.id),
        summary=f"Keyed {inv.reference} by hand",
    )
    await session.commit()
    return inv


async def _fill_vendor_po(session: AsyncSession, inv: FpInvoice) -> None:
    if inv.vendor_code:
        vendor = await session.scalar(select(FpVendor).where(FpVendor.code == inv.vendor_code))
        inv.vendor_name = vendor.name if vendor else inv.vendor_name
    po = await _resolve_po(session, inv.po_reference, inv.vendor_code)
    inv.po_id = po.id if po else None


async def update(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    body: InvoiceIn,
    version: int,
    ctx: RequestContext,
) -> FpInvoice:
    inv = await _load(session, invoice_id, lock=True)
    if inv.version != version:
        raise InvoiceStateError("Someone changed this invoice since you opened it. Reload it.")
    if inv.status not in (InvoiceStatus.CAPTURED, InvoiceStatus.DUPLICATE):
        raise InvoiceStateError(f"{inv.reference} is {inv.status.value}: it can't be edited.")
    _apply(inv, body)
    await _fill_vendor_po(session, inv)
    inv.status = InvoiceStatus.CAPTURED  # an edited duplicate is checked again
    inv.version += 1
    record_event(
        session,
        "fpod.invoice_edited",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        summary=f"Corrected {inv.reference}'s data",
    )
    await session.commit()
    return inv


# --- 3.2 posting agent -------------------------------------------------------------------------


def _check_ready(inv: FpInvoice) -> None:
    missing = [
        label
        for label, ok in (
            ("vendor (from the vendor master)", inv.vendor_code),
            ("invoice number", inv.vendor_invoice_number),
            ("invoice date", inv.invoice_date),
            ("total", inv.total is not None),
            ("lines", inv.lines),
        )
        if not ok
    ]
    if missing:
        raise InvoiceInvalidError("Complete the invoice first: " + ", ".join(missing) + ".")


async def validate_and_post(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    version: int,
    ctx: RequestContext,
    *,
    override_note: str | None = None,
) -> FpInvoice:
    """AP confirms the data (3.1); the posting agent's duplicate guard, then the ERP (3.2);
    then the match agent (3.4)."""
    inv = await _load(session, invoice_id, lock=True)
    if inv.version != version:
        raise InvoiceStateError("Someone changed this invoice since you opened it. Reload it.")
    if override_note is None and inv.status != InvoiceStatus.CAPTURED:
        raise InvoiceStateError(f"{inv.reference} is already {inv.status.value}.")
    if override_note is not None and inv.status != InvoiceStatus.DUPLICATE:
        raise InvoiceStateError(f"{inv.reference} isn't blocked as a duplicate.")
    _check_ready(inv)
    vendor = await session.scalar(select(FpVendor).where(FpVendor.code == inv.vendor_code))
    if vendor is None or vendor.status != VendorStatus.APPROVED or not vendor.active:
        raise InvoiceInvalidError(f"Vendor {inv.vendor_code} isn't active in the vendor master.")
    inv.vendor_name = vendor.name
    if inv.validated_by is None:
        inv.validated_by, inv.validated_at = access.user.id, utcnow()

    if override_note is None:
        others = list(
            await session.scalars(
                select(FpInvoice).where(
                    FpInvoice.vendor_code == inv.vendor_code,
                    FpInvoice.status != InvoiceStatus.REJECTED,
                    FpInvoice.status != InvoiceStatus.CAPTURED,
                )
            )
        )
        hits = agents.duplicates(inv, others)
        if hits:
            inv.status = InvoiceStatus.DUPLICATE
            inv.duplicate = {
                "blocked_at": utcnow().isoformat(),
                "hits": [h.__dict__ for h in hits],
                "explanation": f"Blocked: {hits[0].reason}, as {hits[0].reference} "
                f"({hits[0].status}).",
            }
            inv.version += 1
            record_event(
                session,
                "fpod.invoice_duplicate_blocked",
                ctx,
                actor_id=None,
                run=inv.reference,
                invoice_id=str(inv.id),
                summary=f"Posting agent blocked {inv.reference} as a {hits[0].strength} "
                f"duplicate of {hits[0].reference}: {hits[0].reason}",
            )
            await session.commit()
            return inv
    else:
        inv.duplicate = {
            **(inv.duplicate or {}),
            "overridden_by": access.user.full_name,
            "overridden_at": utcnow().isoformat(),
            "override_note": override_note,
        }
        record_event(
            session,
            "fpod.invoice_duplicate_overridden",
            ctx,
            actor_id=access.user.id,
            run=inv.reference,
            note=override_note,
            summary=f"Released {inv.reference} from the duplicate guard: {override_note}",
        )

    po = await session.get(FpPurchaseOrder, inv.po_id) if inv.po_id else None
    erp = get_erp()
    inv.erp_ref = await erp.create_invoice(
        ErpInvoice(
            number=inv.reference,
            vendor_code=vendor.code,
            vendor_invoice_number=inv.vendor_invoice_number or "",
            po_number=po.reference if po else None,
            currency=inv.currency,
            total=inv.total or Decimal("0"),
            source_filename=inv.filename,
        )
    )
    inv.erp_system, inv.posted_at = erp.name, utcnow()
    inv.status = InvoiceStatus.POSTED
    inv.version += 1
    record_event(
        session,
        "fpod.invoice_posted",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        erp=erp.name,
        summary=f"Posting agent created {inv.reference} in the {erp.name} ERP "
        f"(ref {inv.erp_ref}){' with its source document' if inv.filename else ''}",
    )
    await session.flush()
    await run_match(session, inv, access.user, ctx)
    await session.commit()
    return inv


# --- 3.4 match agent ---------------------------------------------------------------------------


async def _received(session: AsyncSession, po_id: uuid.UUID) -> dict[int, Decimal]:
    rows = await session.execute(
        select(FpReceiptLine.po_line, func.sum(FpReceiptLine.quantity))
        .join(FpReceipt, FpReceipt.id == FpReceiptLine.receipt_id)
        .where(FpReceipt.po_id == po_id)
        .group_by(FpReceiptLine.po_line)
    )
    return dict(rows.all())


async def _invoiced_elsewhere(
    session: AsyncSession, po_id: uuid.UUID, invoice_id: uuid.UUID
) -> dict[int, Decimal]:
    rows = await session.execute(
        select(FpInvoiceLine.po_line, func.sum(FpInvoiceLine.quantity))
        .join(FpInvoice, FpInvoice.id == FpInvoiceLine.invoice_id)
        .where(
            FpInvoice.po_id == po_id,
            FpInvoice.id != invoice_id,
            FpInvoice.status.in_(LIVE),
            FpInvoiceLine.po_line.is_not(None),
        )
        .group_by(FpInvoiceLine.po_line)
    )
    return {line: qty for line, qty in rows.all() if line is not None}


async def run_match(
    session: AsyncSession, inv: FpInvoice, actor: User | None, ctx: RequestContext
) -> dict[str, Any]:
    """Match, then classify (3.4.2): matched -> released to coding; a variance -> an
    exception the exception agent prepares; a missing receipt -> the receipt agent asks."""
    po = await session.get(FpPurchaseOrder, inv.po_id) if inv.po_id else None
    exc = await _current_exception(session, inv)
    credit = (exc.credit_received or Decimal("0")) if exc else Decimal("0")
    settings = await current_settings(session)
    result = agents.match(
        inv,
        po,
        await _received(session, po.id) if po else {},
        await _invoiced_elsewhere(session, po.id, inv.id) if po else {},
        settings,
        credit,
    )
    for row in result["lines"]:  # keep which PO line each invoice line bills
        for ln in inv.lines:
            if ln.position == row["line"]:
                ln.po_line = row["po_line"]
    # A new run replaces the last one, its explanation included (it'd describe old figures)
    inv.match = {**result, "trail": agents.quantity_trail(result), "ran_at": utcnow().isoformat()}
    inv.match_runs += 1
    if inv.first_pass_matched is None:
        inv.first_pass_matched = result["outcome"] == "matched"
    who = actor.id if actor else None
    if result["outcome"] == "matched":
        inv.status, inv.released_at = InvoiceStatus.READY, utcnow()
        if exc is not None and exc.status != ExceptionStatus.RESOLVED:
            exc.status, exc.resolved_at = ExceptionStatus.RESOLVED, utcnow()
        record_event(
            session,
            "fpod.invoice_matched",
            ctx,
            actor_id=who,
            run=inv.reference,
            summary=f"Match agent matched {inv.reference} "
            f"{'(after resolving the exception) ' if inv.match_runs > 1 else ''}"
            "and released it to coding",
        )
        return result

    inv.status = InvoiceStatus.EXCEPTION
    kinds = sorted({i["kind"] for i in result["issues"]})
    if exc is None or exc.status == ExceptionStatus.RESOLVED:
        exc = FpInvoiceException(
            invoice_id=inv.id, status=ExceptionStatus.OPEN, kinds=kinds, issues=result["issues"]
        )
        session.add(exc)
    exc.kinds, exc.issues = kinds, result["issues"]
    if exc.status != ExceptionStatus.WAITING_VENDOR or "price" not in kinds:
        exc.status = (
            ExceptionStatus.WAITING_RECEIPT if set(kinds) & RECEIPT_ISSUES else ExceptionStatus.OPEN
        )
    variance = Decimal(result.get("price_variance") or "0")
    exc.vendor_query_subject, exc.vendor_query_body = agents.vendor_query(
        inv, po, result["issues"], variance if variance > 0 else None
    )
    await session.flush()
    record_event(
        session,
        "fpod.invoice_exception",
        ctx,
        actor_id=who,
        run=inv.reference,
        kinds=kinds,
        summary=f"Match agent found {', '.join(kinds)} on {inv.reference}; exception "
        f"agent prepared the case"
        + (
            "; waiting for the receiver"
            if exc.status == ExceptionStatus.WAITING_RECEIPT
            else "; the buyer decides"
        ),
    )
    if set(kinds) & RECEIPT_ISSUES and po is not None:
        await _ensure_receipt_request(session, po, inv, actor, ctx)
    return result


async def explain_match(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    llm: LLMProvider,
    ctx: RequestContext,
) -> FpInvoice:
    """The match agent explains its last match in plain words, citing computed figures only
    (it can't state a number of its own). Kept until the next match run."""
    inv = await _load(session, invoice_id, lock=True)
    if not inv.match:
        raise InvoiceStateError(f"{inv.reference} hasn't been matched yet.")
    po = await session.get(FpPurchaseOrder, inv.po_id) if inv.po_id else None
    base = {k: v for k, v in inv.match.items() if k not in ("explanation", "explanation_error")}
    try:
        explanation = await agents.explain(llm, inv, po, base)
    except (LLMError, ai.AiOutputRejectedError) as exc:
        reason = (
            exc.message if isinstance(exc, ai.AiOutputRejectedError) else "the AI isn't available"
        )
        inv.match = {**base, "explanation_error": reason}
    else:
        inv.match = {**base, "explanation": {**explanation, "generated_at": utcnow().isoformat()}}
        record_event(
            session,
            "fpod.invoice_explained",
            ctx,
            actor_id=access.user.id,
            run=inv.reference,
            summary=f"Match agent explained {inv.reference}'s match",
        )
    await session.commit()
    return inv


async def rematch(
    session: AsyncSession, access: FinanceAccess, invoice_id: uuid.UUID, ctx: RequestContext
) -> FpInvoice:
    inv = await _load(session, invoice_id, lock=True)
    if inv.status not in (InvoiceStatus.POSTED, InvoiceStatus.EXCEPTION):
        raise InvoiceStateError(f"{inv.reference} is {inv.status.value}: nothing to match.")
    await run_match(session, inv, access.user, ctx)
    inv.version += 1
    await session.commit()
    return inv


# --- 3.5 exceptions: the buyer decides, the agent closes the loop ---------------------------------


async def list_exceptions(
    session: AsyncSession, status: ExceptionStatus | None, open_only: bool
) -> list[ExceptionOut]:
    query = select(FpInvoiceException).order_by(FpInvoiceException.created_at)
    if status is not None:
        query = query.where(FpInvoiceException.status == status)
    elif open_only:
        query = query.where(FpInvoiceException.status != ExceptionStatus.RESOLVED)
    return [await _exception_out(session, e) for e in await session.scalars(query)]


async def decide(
    session: AsyncSession,
    access: FinanceAccess,
    exception_id: uuid.UUID,
    body: DecisionIn,
    ctx: RequestContext,
) -> FpInvoice:
    exc = await session.get(FpInvoiceException, exception_id, with_for_update=True)
    if exc is None:
        raise InvoiceNotFoundError("Exception not found.")
    if exc.status == ExceptionStatus.RESOLVED:
        raise InvoiceStateError("This exception is already resolved.")
    inv = await _load(session, exc.invoice_id, lock=True)
    po = await session.get(FpPurchaseOrder, inv.po_id) if inv.po_id else None
    note = body.note.strip()
    exc.decision, exc.decided_by, exc.decided_at, exc.note = (
        body.decision,
        access.user.id,
        utcnow(),
        note,
    )
    org_sent = None
    if body.decision == ExceptionDecision.ACCEPT:
        if set(exc.kinds) & (RECEIPT_ISSUES | {"no_po", "not_on_po"}):
            raise InvoiceInvalidError(
                "Not everything billed is received (or on the PO): the receiver confirms "
                "first, or amend the PO, credit or reject."
            )
        exc.status, exc.resolved_at = ExceptionStatus.RESOLVED, utcnow()
        inv.status, inv.released_at = InvoiceStatus.READY, utcnow()
        what = f"accepted the variance and released {inv.reference} to coding"
    elif body.decision == ExceptionDecision.CREDIT:
        variance = Decimal((inv.match or {}).get("price_variance") or "0")
        exc.credit_expected = body.credit_expected or (variance if variance > 0 else None)
        if not exc.credit_expected:
            raise InvoiceInvalidError("Say how much credit to ask for.")
        subject, text = agents.vendor_query(inv, po, exc.issues, exc.credit_expected)
        org_sent = await _send_query(
            session, access, inv, po, body.query_subject or subject, body.query_body or text
        )
        exc.status = ExceptionStatus.WAITING_VENDOR
        what = f"asked {inv.vendor_name} for a credit note of {exc.credit_expected}"
    elif body.decision == ExceptionDecision.AMEND_PO:
        if po is None:
            raise InvoiceInvalidError("This invoice has no PO to amend.")
        if po.status not in (PoStatus.ISSUED, PoStatus.ACKNOWLEDGED):
            raise InvoiceStateError(f"{po.reference} is {po.status.value}: it can't be amended.")
        lines = {ln.position: ln for ln in po.lines}
        changes = []
        for a in body.amendments:
            target = lines.get(a.po_line)
            if target is None:
                raise InvoiceInvalidError(f"{po.reference} has no line {a.po_line}.")
            if target.unit_price == a.unit_price and target.quantity == a.quantity:
                continue
            session.add(
                FpPoAmendment(
                    po_id=po.id,
                    exception_id=exc.id,
                    position=a.po_line,
                    old_unit_price=target.unit_price,
                    new_unit_price=a.unit_price,
                    old_quantity=target.quantity,
                    new_quantity=a.quantity,
                    note=note,
                    amended_by=access.user.id,
                )
            )
            changes.append(
                f"line {a.po_line}: {target.quantity} x {target.unit_price} -> "
                f"{a.quantity} x {a.unit_price}"
            )
            # The only place a PO line's price changes: a person's decision, recorded above
            target.unit_price, target.quantity = a.unit_price, a.quantity
            target.price_source = "buyer"
        if not changes:
            raise InvoiceInvalidError("The amendments change nothing on the PO.")
        po.version += 1
        record_event(
            session,
            "fpod.po_amended",
            ctx,
            actor_id=access.user.id,
            po=po.reference,
            changes=changes,
            summary=f"Buyer amended {po.reference} for {inv.reference}: "
            + "; ".join(changes)
            + f". {note}",
        )
        await session.flush()
        await session.refresh(po, ["lines"])
        what = f"amended {po.reference}"
    else:  # reject
        subject = f"Your invoice {inv.vendor_invoice_number or ''}: rejected"
        text = (
            f"Hello {inv.vendor_name or 'there'},\n\nWe have rejected your invoice "
            f"{inv.vendor_invoice_number or ''}: {note}\n\nThank you,\n"
            f"{get_settings().email_sender_name}"
        )
        org_sent = await _send_query(
            session, access, inv, po, body.query_subject or subject, body.query_body or text
        )
        exc.status, exc.resolved_at = ExceptionStatus.RESOLVED, utcnow()
        inv.status, inv.rejected_reason = InvoiceStatus.REJECTED, note
        what = f"rejected {inv.reference}"
    inv.version += 1
    record_event(
        session,
        "fpod.invoice_exception_decided",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        decision=body.decision.value,
        note=note,
        summary=f"Buyer {what}: {note}" + (mail.outcome(org_sent) if org_sent is not None else ""),
    )
    if body.decision == ExceptionDecision.AMEND_PO:
        await run_match(session, inv, access.user, ctx)  # close the loop (3.5.3)
    await session.commit()
    return inv


async def _send_query(
    session: AsyncSession,
    access: FinanceAccess,
    inv: FpInvoice,
    po: FpPurchaseOrder | None,
    subject: str,
    body: str,
) -> mail.FpEmail:
    vendor = await session.scalar(select(FpVendor).where(FpVendor.code == inv.vendor_code))
    to = (po.vendor_email if po else None) or (vendor.email if vendor else None)
    if not to:
        raise InvoiceInvalidError("The vendor has no email to send the query to.")
    return await mail.send(
        session,
        kind=mail.MailKind.VENDOR_QUERY,
        to_email=to,
        to_name=inv.vendor_name,
        subject=subject,
        body=body,
        sent_by=access.user.id,
        request_id=po.request_id if po else None,
    )


async def credit_note(
    session: AsyncSession,
    access: FinanceAccess,
    exception_id: uuid.UUID,
    amount: Decimal,
    reference: str,
    ctx: RequestContext,
) -> FpInvoice:
    """The vendor's credit note arrived: record it and close the loop (3.5.3)."""
    exc = await session.get(FpInvoiceException, exception_id, with_for_update=True)
    if exc is None:
        raise InvoiceNotFoundError("Exception not found.")
    if exc.status != ExceptionStatus.WAITING_VENDOR:
        raise InvoiceStateError("This exception isn't waiting for a credit note.")
    inv = await _load(session, exc.invoice_id, lock=True)
    exc.credit_received = (exc.credit_received or Decimal("0")) + amount
    exc.credit_note_ref = reference
    record_event(
        session,
        "fpod.invoice_credit_note",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        summary=f"Recorded credit note {reference} ({amount}) for {inv.reference}",
    )
    await session.flush()
    await run_match(session, inv, access.user, ctx)
    if inv.status == InvoiceStatus.EXCEPTION and exc.credit_received < (exc.credit_expected or 0):
        exc.status = ExceptionStatus.WAITING_VENDOR  # still short of what was asked
    inv.version += 1
    await session.commit()
    return inv


async def delete_invoices(
    session: AsyncSession, access: FinanceAccess, ids: list[uuid.UUID], ctx: RequestContext
) -> int:
    """Remove invoices (e.g. to run a demo again): with their lines and exceptions; open
    receipt requests for them are cancelled. Receipts stay on the PO (they're the delivery's).
    The audit trail keeps a record of each one."""
    invoices = list(
        await session.scalars(select(FpInvoice).where(FpInvoice.id.in_(ids)).with_for_update())
    )
    if not invoices:
        raise InvoiceNotFoundError
    from src.app.finance_pod.payments.models import FpPaymentItem

    in_runs = set(
        await session.scalars(
            select(FpPaymentItem.invoice_id).where(
                FpPaymentItem.invoice_id.in_([i.id for i in invoices])
            )
        )
    )
    if in_runs:
        refs = ", ".join(i.reference for i in invoices if i.id in in_runs)
        raise InvoiceStateError(
            f"{refs}: in a payment run, so kept for the payment record. Cancel the run first "
            "if it isn't released; paid invoices stay."
        )
    for inv in invoices:
        for req in await session.scalars(
            select(FpReceiptRequest).where(
                FpReceiptRequest.invoice_id == inv.id,
                FpReceiptRequest.status == ReceiptRequestStatus.OPEN,
            )
        ):
            req.status, req.token_hash = ReceiptRequestStatus.CANCELLED, None
        record_event(
            session,
            "fpod.invoice_deleted",
            ctx,
            actor_id=access.user.id,
            run=inv.reference,
            vendor=inv.vendor_name,
            vendor_invoice_number=inv.vendor_invoice_number,
            total=str(inv.total) if inv.total is not None else None,
            status=inv.status.value,
            summary=f"Deleted {inv.reference} ({inv.vendor_name or 'vendor ?'} "
            f"{inv.vendor_invoice_number or ''}, {inv.total if inv.total is not None else '?'} "
            f"{inv.currency}, was {inv.status.value})",
        )
        await session.delete(inv)
    await session.commit()
    return len(invoices)


async def reject(
    session: AsyncSession,
    access: FinanceAccess,
    invoice_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> FpInvoice:
    inv = await _load(session, invoice_id, lock=True)
    if inv.status in (InvoiceStatus.READY, InvoiceStatus.REJECTED):
        raise InvoiceStateError(f"{inv.reference} is already {inv.status.value}.")
    inv.status, inv.rejected_reason = InvoiceStatus.REJECTED, reason
    exc = await _current_exception(session, inv)
    if exc is not None and exc.status != ExceptionStatus.RESOLVED:
        exc.status, exc.resolved_at = ExceptionStatus.RESOLVED, utcnow()
        exc.decision, exc.decided_by, exc.decided_at, exc.note = (
            ExceptionDecision.REJECT,
            access.user.id,
            utcnow(),
            reason,
        )
    inv.version += 1
    record_event(
        session,
        "fpod.invoice_rejected",
        ctx,
        actor_id=access.user.id,
        run=inv.reference,
        summary=f"Rejected {inv.reference}: {reason}",
    )
    await session.commit()
    return inv


# --- 3.6 receipt agent ---------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def receipt_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/receipt/{token}"


async def _receiver(session: AsyncSession, po: FpPurchaseOrder) -> tuple[str, str]:
    """Who received it: the requester of the PO's request."""
    request = await session.get(FpPurchaseRequest, po.request_id)
    user = await session.get(User, request.requester_id) if request else None
    if user is None:
        raise InvoiceInvalidError("The PO's requester has no account to ask for the receipt.")
    return user.email, user.full_name


async def _send_link(
    session: AsyncSession,
    req: FpReceiptRequest,
    po: FpPurchaseOrder,
    inv: FpInvoice | None,
    sent_by: uuid.UUID,
) -> str:
    token = secrets.token_urlsafe(32)
    req.token_hash = _hash(token)
    req.expires_at = utcnow() + timedelta(days=RECEIPT_LINK_DAYS)
    req.nudges += 1
    req.last_nudged_at = utcnow()
    org = get_settings().email_sender_name
    body = (
        f"Hello {req.receiver_name or ''},\n\n{po.vendor_name} has invoiced {po.reference}"
        f"{f' ({inv.reference})' if inv else ''}, but we have no record that it arrived.\n\n"
        f"Please confirm what you received, from your phone, in under a minute:\n\n"
        f"{receipt_url(token)}\n\nThe invoice is on hold until you do.\n\n{org}"
    )
    await mail.send(
        session,
        kind=mail.MailKind.RECEIPT_REQUEST,
        to_email=req.receiver_email,
        to_name=req.receiver_name,
        subject=f"Did {po.reference} arrive? Please confirm",
        body=body,
        sent_by=sent_by,
        request_id=po.request_id,
    )
    return token


async def _ensure_receipt_request(
    session: AsyncSession,
    po: FpPurchaseOrder,
    inv: FpInvoice,
    actor: User | None,
    ctx: RequestContext,
) -> None:
    open_req = await session.scalar(
        select(FpReceiptRequest).where(
            FpReceiptRequest.po_id == po.id, FpReceiptRequest.status == ReceiptRequestStatus.OPEN
        )
    )
    if open_req is not None:
        return
    email, name = await _receiver(session, po)
    req = FpReceiptRequest(
        po_id=po.id,
        invoice_id=inv.id,
        receiver_email=email,
        receiver_name=name,
        status=ReceiptRequestStatus.OPEN,
    )
    session.add(req)
    await session.flush()
    await _send_link(session, req, po, inv, actor.id if actor else inv.created_by)
    record_event(
        session,
        "fpod.receipt_requested",
        ctx,
        actor_id=None,
        run=inv.reference,
        po=po.reference,
        summary=f"Receipt agent asked {name} ({email}) to confirm what of {po.reference} arrived",
    )


async def nudge(
    session: AsyncSession, access: FinanceAccess, request_id: uuid.UUID, ctx: RequestContext
) -> tuple[FpReceiptRequest, str]:
    req = await session.get(FpReceiptRequest, request_id, with_for_update=True)
    if req is None:
        raise InvoiceNotFoundError("Receipt request not found.")
    if req.status != ReceiptRequestStatus.OPEN:
        raise InvoiceStateError("This receipt was already confirmed.")
    po = await session.get(FpPurchaseOrder, req.po_id)
    assert po is not None  # noqa: S101 - cascade
    inv = await session.get(FpInvoice, req.invoice_id) if req.invoice_id else None
    token = await _send_link(session, req, po, inv, access.user.id)
    record_event(
        session,
        "fpod.receipt_nudged",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        summary=f"Receipt agent nudged {req.receiver_name} again for {po.reference} "
        f"(nudge {req.nudges})",
    )
    await session.commit()
    return req, token


async def _by_token(session: AsyncSession, token: str) -> FpReceiptRequest:
    if not token or len(token) > 100:
        raise ReceiptLinkError
    req = await session.scalar(
        select(FpReceiptRequest)
        .where(FpReceiptRequest.token_hash == _hash(token))
        .with_for_update()
    )
    if req is None:
        raise ReceiptLinkError
    return req


async def _po_lines_view(session: AsyncSession, po: FpPurchaseOrder) -> list[dict[str, Any]]:
    got = await _received(session, po.id)
    return [
        {
            "position": ln.position,
            "description": ln.description,
            "ordered": str(ln.quantity),
            "unit": ln.unit,
            "received": str(got.get(ln.position, Decimal("0"))),
        }
        for ln in po.lines
    ]


async def portal_view(session: AsyncSession, token: str) -> ReceiptPortalView:
    req = await _by_token(session, token)
    po = await session.get(FpPurchaseOrder, req.po_id)
    assert po is not None  # noqa: S101
    inv = await session.get(FpInvoice, req.invoice_id) if req.invoice_id else None
    expired = req.expires_at is not None and req.expires_at < utcnow()
    return ReceiptPortalView(
        status="used"
        if req.status != ReceiptRequestStatus.OPEN
        else "expired"
        if expired
        else "open",
        organisation=get_settings().email_sender_name,
        po_reference=po.reference,
        vendor_name=po.vendor_name,
        receiver_name=req.receiver_name,
        invoice_reference=inv.reference if inv else None,
        lines=await _po_lines_view(session, po),
    )


async def _record_receipt(
    session: AsyncSession,
    po: FpPurchaseOrder,
    body: ReceiptIn,
    *,
    via: str,
    receiver_email: str | None,
    recorded_by: uuid.UUID | None,
    ctx: RequestContext,
) -> FpReceipt:
    if po.status not in (PoStatus.ISSUED, PoStatus.ACKNOWLEDGED):
        raise InvoiceStateError(f"{po.reference} isn't issued: nothing can be received on it.")
    positions = {ln.position for ln in po.lines}
    unknown = [ln.po_line for ln in body.lines if ln.po_line not in positions]
    if unknown:
        raise InvoiceInvalidError(f"{po.reference} has no line {unknown[0]}.")
    # Not more than was ordered: an over-delivery goes back to the buyer (amend the PO)
    got = await _received(session, po.id)
    ordered = {ln.position: ln.quantity for ln in po.lines}
    over = [
        f"line {ln.po_line}: {ln.quantity.normalize():f} more would make "
        f"{(got.get(ln.po_line, Decimal('0')) + ln.quantity).normalize():f} of "
        f"{ordered[ln.po_line].normalize():f} ordered"
        for ln in body.lines
        if got.get(ln.po_line, Decimal("0")) + ln.quantity > ordered[ln.po_line]
    ]
    if over:
        raise InvoiceInvalidError(
            f"More than {po.reference} ordered ({'; '.join(over)}). If more really arrived, "
            "the buyer amends the PO first."
        )
    lines = [
        FpReceiptLine(po_line=ln.po_line, quantity=ln.quantity)
        for ln in body.lines
        if ln.quantity > 0
    ]
    if not lines:
        raise InvoiceInvalidError("Enter what was received (a quantity above 0).")
    if body.received_on > utcnow().date():
        raise InvoiceInvalidError("The date received is in the future.")
    receipt = FpReceipt(
        po_id=po.id,
        received_on=body.received_on,
        receiver_email=receiver_email,
        recorded_by=recorded_by,
        via=via,
        notes=body.notes.strip() or None,
        lines=lines,
    )
    session.add(receipt)
    await session.flush()
    record_event(
        session,
        "fpod.receipt_recorded",
        ctx,
        actor_id=recorded_by,
        po=po.reference,
        summary=f"Receipt for {po.reference} recorded ({via.replace('_', ' ')}): "
        + ", ".join(f"line {ln.po_line} x {ln.quantity.normalize():f}" for ln in lines),
    )
    # Close the loop: invoices of this PO waiting on a receipt are matched again
    waiting = await session.scalars(
        select(FpInvoice).where(
            FpInvoice.po_id == po.id,
            FpInvoice.status.in_([InvoiceStatus.EXCEPTION, InvoiceStatus.POSTED]),
        )
    )
    for inv in waiting:
        await run_match(session, inv, None, ctx)
        inv.version += 1
    return receipt


async def portal_confirm(
    session: AsyncSession, token: str, body: ReceiptIn, ctx: RequestContext
) -> None:
    """The receiver confirms on the phone (3.6.2); the match agent re-runs."""
    req = await _by_token(session, token)
    if req.status != ReceiptRequestStatus.OPEN:
        raise ReceiptLinkError("This was already confirmed. Thank you.")
    if req.expires_at and req.expires_at < utcnow():
        raise ReceiptLinkError("This link has expired.")
    po = await session.get(FpPurchaseOrder, req.po_id)
    assert po is not None  # noqa: S101
    receipt = await _record_receipt(
        session,
        po,
        body,
        via="mobile_link",
        receiver_email=req.receiver_email,
        recorded_by=None,
        ctx=ctx,
    )
    req.status, req.confirmed_at = ReceiptRequestStatus.CONFIRMED, utcnow()
    req.token_hash, req.receipt_id = None, receipt.id
    await session.commit()


async def record_receipt(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    body: ReceiptIn,
    ctx: RequestContext,
) -> None:
    po = await session.get(FpPurchaseOrder, po_id, with_for_update=True)
    if po is None:
        raise InvoiceNotFoundError("Purchase order not found.")
    await _record_receipt(
        session,
        po,
        body,
        via="app",
        receiver_email=access.user.email,
        recorded_by=access.user.id,
        ctx=ctx,
    )
    for req in await session.scalars(
        select(FpReceiptRequest).where(
            FpReceiptRequest.po_id == po.id, FpReceiptRequest.status == ReceiptRequestStatus.OPEN
        )
    ):
        req.status, req.confirmed_at, req.token_hash = (
            ReceiptRequestStatus.CONFIRMED,
            utcnow(),
            None,
        )
    await session.commit()


async def receipts(session: AsyncSession, po_id: uuid.UUID) -> list[ReceiptOut]:
    rows = await session.scalars(
        select(FpReceipt).where(FpReceipt.po_id == po_id).order_by(FpReceipt.created_at)
    )
    return [
        ReceiptOut(
            id=r.id,
            received_on=r.received_on,
            receiver_email=r.receiver_email,
            via=r.via,
            notes=r.notes,
            created_at=r.created_at,
            lines=[{"po_line": ln.po_line, "quantity": str(ln.quantity)} for ln in r.lines],
        )
        for r in rows
    ]


# --- measures ----------------------------------------------------------------------------------


async def measures(session: AsyncSession) -> dict[str, Any]:
    invoices = list(await session.scalars(select(FpInvoice)))
    judged = [i for i in invoices if i.first_pass_matched is not None]
    first_pass = sum(1 for i in judged if i.first_pass_matched)
    exceptions = list(await session.scalars(select(FpInvoiceException)))
    open_ = [e for e in exceptions if e.status != ExceptionStatus.RESOLVED]
    buckets = {"0-7 days": 0, "8-14 days": 0, "15-30 days": 0, "over 30 days": 0}
    for e in open_:
        age = _age(e)
        key = (
            "0-7 days"
            if age <= 7
            else "8-14 days"
            if age <= 14
            else "15-30 days"
            if age <= 30
            else "over 30 days"
        )
        buckets[key] += 1
    by_kind: dict[str, int] = defaultdict(int)
    for e in open_:
        for k in e.kinds:
            by_kind[k] += 1
    blocked = [
        i
        for i in invoices
        if i.duplicate and i.duplicate.get("hits") and not i.duplicate.get("overridden_by")
    ]
    return {
        "invoices": len(invoices),
        "first_pass_judged": len(judged),
        "first_pass_matched": first_pass,
        "first_pass_rate": round(first_pass / len(judged), 3) if judged else None,
        "exceptions_open": len(open_),
        "exception_ageing": buckets,
        "exceptions_by_kind": dict(by_kind),
        "oldest_open_days": max((_age(e) for e in open_), default=None),
        "duplicates_stopped": len(blocked),
        "duplicates_amount": str(sum((i.total or Decimal("0") for i in blocked), Decimal("0"))),
        "ready_for_coding": sum(1 for i in invoices if i.status == InvoiceStatus.READY),
    }
