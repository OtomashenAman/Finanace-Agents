"""Vendor selection (Phase 1.3): the sourcing agent prepares, the buyer chooses.

Rules: sourcing only for an approved request; at or above the purchasing threshold the
buyer needs the required number of received quotes, or a written justification (sole
source...); an expired quote can't be chosen; a blocked vendor never. Choosing a vendor
that isn't in the vendor master starts its onboarding (1.5): the portal link goes to the
vendor and the PO waits until the vendor is active.
"""

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.finance_pod import mail
from src.app.finance_pod.access import FinanceAccess
from src.app.finance_pod.reference.models import FpVendor, VendorStatus
from src.app.finance_pod.requests.agent import Reference
from src.app.finance_pod.requests.exceptions import (
    RequestInvalidError,
    RequestLockedError,
    RequestNotFoundError,
)
from src.app.finance_pod.requests.models import FpPurchaseRequest, RequestStatus
from src.app.finance_pod.settings.service import current as current_settings
from src.app.finance_pod.sourcing import agent
from src.app.finance_pod.sourcing.models import FpQuote, FpSourcing, QuoteStatus, SourcingStatus
from src.app.finance_pod.sourcing.schemas import (
    Candidate,
    ChooseIn,
    EmailOut,
    NewQuoteIn,
    QuoteIn,
    QuoteOut,
    QuoteRequestIn,
    SourcingOut,
    VendorRef,
)
from src.app.service_pod.common import ai

QUOTE_FILE_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def _request(session: AsyncSession, request_id: uuid.UUID) -> FpPurchaseRequest:
    request = await session.get(FpPurchaseRequest, request_id, with_for_update=True)
    if request is None:
        raise RequestNotFoundError
    return request


async def _po_exists(session: AsyncSession, request_id: uuid.UUID) -> bool:
    from src.app.finance_pod.orders.models import FpPurchaseOrder, PoStatus

    return bool(
        await session.scalar(
            select(FpPurchaseOrder.id).where(
                FpPurchaseOrder.request_id == request_id,
                FpPurchaseOrder.status != PoStatus.CANCELLED,
            )
        )
    )


async def start(session: AsyncSession, request: FpPurchaseRequest) -> FpSourcing:
    """Run the sourcing agent for an approved request (once; `refresh` re-runs it)."""
    sourcing = await session.scalar(select(FpSourcing).where(FpSourcing.request_id == request.id))
    if sourcing is None:
        sourcing = FpSourcing(request_id=request.id, status=SourcingStatus.OPEN)
        session.add(sourcing)
    settings = await current_settings(session)
    ref = await Reference.load(session)
    found = agent.candidates(request, ref, utcnow().date())
    sourcing.candidates = {
        "ran_at": utcnow().isoformat(),
        "vendors": [c.model_dump(mode="json") for c in found],
    }
    sourcing.quotes_needed = (
        settings.min_quotes if request.total >= settings.purchasing_threshold else 0
    )
    return sourcing


async def _sourcing(session: AsyncSession, request: FpPurchaseRequest) -> FpSourcing:
    if request.status not in (RequestStatus.APPROVED, RequestStatus.ORDERED):
        raise RequestLockedError(f"{request.reference} isn't approved, so there's no sourcing.")
    sourcing = await session.scalar(select(FpSourcing).where(FpSourcing.request_id == request.id))
    return sourcing or await start(session, request)


async def view(session: AsyncSession, request_id: uuid.UUID) -> SourcingOut:
    request = await session.get(FpPurchaseRequest, request_id)
    if request is None:
        raise RequestNotFoundError
    sourcing = await _sourcing(session, request)
    await session.commit()  # a first look runs the agent
    quotes = list(
        await session.scalars(
            select(FpQuote).where(FpQuote.request_id == request.id).order_by(FpQuote.created_at)
        )
    )
    cands = [Candidate.model_validate(c) for c in sourcing.candidates.get("vendors", [])]
    known = set(
        await session.scalars(select(FpVendor.code).where(FpVendor.status == VendorStatus.APPROVED))
    )
    emails = await session.scalars(
        select(mail.FpEmail)
        .where(
            mail.FpEmail.request_id == request.id,
            mail.FpEmail.kind == mail.MailKind.QUOTE_REQUEST,
        )
        .order_by(mail.FpEmail.created_at)
    )
    decider = await session.get(User, sourcing.decided_by) if sourcing.decided_by else None
    return SourcingOut(
        status=sourcing.status,
        quotes_needed=sourcing.quotes_needed,
        quotes_received=sum(1 for q in quotes if q.status == QuoteStatus.RECEIVED),
        candidates=cands,
        quotes=[QuoteOut.model_validate(q, from_attributes=True) for q in quotes],
        comparison=agent.comparison(request, quotes, cands, known, utcnow().date()),
        chosen_quote_id=sourcing.chosen_quote_id,
        chosen_vendor_code=sourcing.chosen_vendor_code,
        chosen_vendor_name=sourcing.chosen_vendor_name,
        chosen_total=sourcing.chosen_total,
        payment_terms=sourcing.payment_terms,
        delivery_date=sourcing.delivery_date,
        justification=sourcing.justification,
        onboarding_id=sourcing.onboarding_id,
        decided_at=sourcing.decided_at,
        decided_by_name=decider.full_name if decider else None,
        can_change=not await _po_exists(session, request.id),
        emails=[EmailOut.model_validate(e, from_attributes=True) for e in emails],
    )


async def _vendor(session: AsyncSession, ref: VendorRef) -> tuple[str | None, str, str | None]:
    """(code, name, email) of an approved vendor, or a new one (code None)."""
    if ref.vendor_code:
        vendor = await session.scalar(select(FpVendor).where(FpVendor.code == ref.vendor_code))
        if vendor is None:
            raise RequestInvalidError(f"Vendor {ref.vendor_code} isn't in the vendor master.")
        if vendor.status == VendorStatus.BLOCKED or not vendor.active:
            raise RequestInvalidError(f"Vendor {vendor.code} is blocked.")
        return vendor.code, vendor.name, ref.vendor_email or vendor.email
    assert ref.vendor_name and ref.vendor_email  # noqa: S101 - VendorRef validates
    return None, ref.vendor_name.strip(), str(ref.vendor_email).lower()


async def _guard_open(session: AsyncSession, request: FpPurchaseRequest) -> FpSourcing:
    sourcing = await _sourcing(session, request)
    if await _po_exists(session, request.id):
        raise RequestLockedError("The PO is already drafted: sourcing is closed.")
    return sourcing


async def refresh(
    session: AsyncSession, access: FinanceAccess, request_id: uuid.UUID, ctx: RequestContext
) -> None:
    request = await _request(session, request_id)
    await _guard_open(session, request)
    await start(session, request)
    record_event(
        session,
        "fpod.sourcing_refreshed",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        summary=f"Sourcing agent re-ran for {request.reference}",
    )
    await session.commit()


async def request_quotes(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    body: QuoteRequestIn,
    ctx: RequestContext,
) -> list[str]:
    """Send the agent's quote request to each vendor (1.3.1.b); returns how each went."""
    request = await _request(session, request_id)
    await _guard_open(session, request)
    if body.reply_by < utcnow().date():
        raise RequestInvalidError("The reply-by date is in the past.")
    outcomes = []
    for ref in body.vendors:
        code, name, email = await _vendor(session, ref)
        if not email:
            raise RequestInvalidError(f"Vendor {code} has no email address in the vendor master.")
        subject, text = agent.quote_request_email(request, name, body.reply_by, body.message)
        row = await mail.send(
            session,
            kind=mail.MailKind.QUOTE_REQUEST,
            to_email=email,
            to_name=name,
            subject=subject,
            body=text,
            sent_by=access.user.id,
            request_id=request.id,
        )
        if row.status != mail.MailStatus.FAILED:
            session.add(
                FpQuote(
                    request_id=request.id,
                    vendor_code=code,
                    vendor_name=name,
                    vendor_email=email,
                    status=QuoteStatus.REQUESTED,
                    requested_at=utcnow(),
                    created_by=access.user.id,
                )
            )
        outcomes.append(f"{name}: {row.status.value}{mail.outcome(row)}")
        record_event(
            session,
            "fpod.quote_requested",
            ctx,
            actor_id=access.user.id,
            run=request.reference,
            to=email,
            status=row.status.value,
            summary=f"Requested a quote for {request.reference} from {name} ({email})"
            + mail.outcome(row),
        )
    await session.commit()
    return outcomes


async def _quote(session: AsyncSession, request_id: uuid.UUID, quote_id: uuid.UUID) -> FpQuote:
    quote = await session.get(FpQuote, quote_id)
    if quote is None or quote.request_id != request_id:
        raise RequestNotFoundError("Quote not found.")
    return quote


def _apply(quote: FpQuote, body: QuoteIn) -> None:
    quote.status = body.status
    quote.total = body.total
    quote.currency = body.currency
    quote.lead_time_days = body.lead_time_days
    quote.payment_terms = body.payment_terms
    quote.valid_until = body.valid_until
    quote.notes = body.notes
    if body.status == QuoteStatus.RECEIVED:
        quote.received_at = quote.received_at or utcnow()
        if quote.total is None:
            raise RequestInvalidError("A received quote needs its total.")


async def add_quote(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    body: NewQuoteIn,
    ctx: RequestContext,
) -> None:
    """A quote that came in without a request from us (or by phone, from a portal...)."""
    request = await _request(session, request_id)
    await _guard_open(session, request)
    code, name, email = await _vendor(session, body)
    quote = FpQuote(
        request_id=request.id,
        vendor_code=code,
        vendor_name=name,
        vendor_email=email,
        status=QuoteStatus.RECEIVED,
        created_by=access.user.id,
    )
    _apply(quote, body)
    session.add(quote)
    record_event(
        session,
        "fpod.quote_recorded",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        summary=f"Recorded {name}'s quote for "
        f"{request.reference}: {quote.total} {quote.currency or request.currency}",
    )
    await session.commit()


async def update_quote(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    body: QuoteIn,
    ctx: RequestContext,
) -> None:
    request = await _request(session, request_id)
    await _guard_open(session, request)
    quote = await _quote(session, request.id, quote_id)
    _apply(quote, body)
    record_event(
        session,
        "fpod.quote_recorded",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        summary=f"Recorded {quote.vendor_name}'s quote for "
        f"{request.reference}: {quote.status.value}"
        + (f", {quote.total} {quote.currency or request.currency}" if quote.total else ""),
    )
    await session.commit()


async def attach_quote_file(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
    llm: LLMProvider,
    ctx: RequestContext,
) -> str | None:
    """Keep the quote document and let the agent read it. Returns why the reading failed,
    if it did (the file is kept either way; the buyer types the figures)."""
    request = await _request(session, request_id)
    await _guard_open(session, request)
    quote = await _quote(session, request.id, quote_id)
    content_type = content_type.split(";")[0].strip().lower()
    if content_type not in QUOTE_FILE_TYPES:
        raise RequestInvalidError("Allowed: PDF, PNG, JPEG, TXT, XLSX or DOCX.")
    if not data:
        raise RequestInvalidError("The file is empty.")
    quote.filename, quote.content_type, quote.content = filename[:255], content_type, data
    quote.sha256 = hashlib.sha256(data).hexdigest()
    problem = None
    try:
        read = await agent.read_quote(llm, data, filename)
    except (LLMError, ai.AiOutputRejectedError) as exc:
        problem = exc.message if isinstance(exc, ai.AiOutputRejectedError) else "AI unavailable"
        read = None
    if read is not None:
        quote.ai_read = read
        # Fill what the buyer hasn't typed; never overwrite a person's figure
        if quote.total is None:
            quote.total = agent.parse_total(read.get("total"))
        if quote.currency is None and isinstance(read.get("currency"), str):
            quote.currency = str(read["currency"])[:3].upper()
        if quote.lead_time_days is None and isinstance(read.get("lead_time_days"), int):
            quote.lead_time_days = int(read["lead_time_days"])  # type: ignore[call-overload]
        if quote.payment_terms is None and read.get("payment_terms"):
            quote.payment_terms = str(read["payment_terms"])[:200]
        if quote.valid_until is None:
            quote.valid_until = agent.parse_date(read.get("valid_until"))
        if quote.total is not None and quote.status == QuoteStatus.REQUESTED:
            quote.status, quote.received_at = QuoteStatus.RECEIVED, utcnow()
    record_event(
        session,
        "fpod.quote_read",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        summary=f"Sourcing agent read {quote.vendor_name}'s quote for {request.reference}"
        + (f": total {quote.total}" if read and quote.total is not None else "")
        + ("" if read is None or read.get("verified") else " (from an image: confirm it)")
        + (f"; couldn't read it ({problem})" if problem else ""),
    )
    await session.commit()
    return problem


async def quote_file(
    session: AsyncSession, request_id: uuid.UUID, quote_id: uuid.UUID
) -> tuple[str, str, bytes]:
    quote = await _quote(session, request_id, quote_id)
    content = await session.scalar(select(FpQuote.content).where(FpQuote.id == quote.id))
    if not content or not quote.filename:
        raise RequestNotFoundError("This quote has no document.")
    return quote.filename, quote.content_type or "application/octet-stream", content


async def choose(
    session: AsyncSession,
    access: FinanceAccess,
    request_id: uuid.UUID,
    body: ChooseIn,
    ctx: RequestContext,
) -> None:
    """The buyer confirms vendor and terms (1.3.2)."""
    from src.app.finance_pod.onboarding import service as onboarding

    request = await _request(session, request_id)
    sourcing = await _guard_open(session, request)
    today = utcnow().date()
    quotes = list(await session.scalars(select(FpQuote).where(FpQuote.request_id == request.id)))
    received = sum(1 for q in quotes if q.status == QuoteStatus.RECEIVED)
    justification = body.justification.strip()

    if body.quote_id:
        quote = await _quote(session, request.id, body.quote_id)
        if quote.status != QuoteStatus.RECEIVED or quote.total is None:
            raise RequestInvalidError("Only a received quote with a total can be chosen.")
        if quote.valid_until and quote.valid_until < today:
            raise RequestInvalidError(
                f"{quote.vendor_name}'s quote expired on {quote.valid_until}."
            )
        if quote.currency and quote.currency != request.currency:
            raise RequestInvalidError(
                f"The quote is in {quote.currency}, the request in "
                f"{request.currency}: ask for a quote in {request.currency}."
            )
        code, name, email, total = (
            quote.vendor_code,
            quote.vendor_name,
            quote.vendor_email,
            quote.total,
        )
        if received < sourcing.quotes_needed and len(justification) < 15:
            raise RequestInvalidError(
                f"{sourcing.quotes_needed} quotes are required at or above the purchasing "
                f"threshold and {received} came in: explain why this choice is right "
                "(e.g. sole source) in the justification."
            )
    else:
        cands = [Candidate.model_validate(c) for c in sourcing.candidates.get("vendors", [])]
        cand = next((c for c in cands if c.vendor_code == body.contract_vendor_code), None)
        if cand is None or not cand.covers_all_lines or cand.contract_total is None:
            raise RequestInvalidError(
                "That vendor doesn't have contract prices for every line: choose a quote."
            )
        code, name, email, total = (
            cand.vendor_code,
            cand.vendor_name,
            cand.vendor_email,
            cand.contract_total,
        )
        if not justification:
            refs = sorted({str(x) for x in cand.reasons})
            justification = "Contract prices: " + "; ".join(refs)

    vendor = await session.scalar(select(FpVendor).where(FpVendor.code == code)) if code else None
    if vendor is not None and (vendor.status == VendorStatus.BLOCKED or not vendor.active):
        raise RequestInvalidError(f"Vendor {vendor.code} is blocked.")

    sourcing.chosen_quote_id = body.quote_id
    sourcing.chosen_vendor_code = vendor.code if vendor else None
    sourcing.chosen_vendor_name = name
    sourcing.chosen_vendor_email = email
    sourcing.chosen_total = total
    sourcing.payment_terms = body.payment_terms.strip()
    sourcing.delivery_date = body.delivery_date or request.needed_by
    sourcing.justification = justification or None
    sourcing.decided_by = access.user.id
    sourcing.decided_at = utcnow()
    if vendor is not None:
        sourcing.status = SourcingStatus.CHOSEN
        what = f"Chose {name} for {request.reference} at {total} {request.currency}"
        # An onboarding started for an earlier choice isn't needed any more
        await onboarding.reuse_or_retire(session, access, sourcing.onboarding_id, None, ctx)
        sourcing.onboarding_id = None
    else:
        if not email:
            raise RequestInvalidError("The new vendor needs an email for the onboarding portal.")
        # Choosing again: the same vendor keeps its onboarding; a different one retires it
        reused = await onboarding.reuse_or_retire(
            session, access, sourcing.onboarding_id, email, ctx
        )
        if reused is None:
            reused, _ = await onboarding.invite(
                session,
                access,
                vendor_name=name,
                vendor_email=email,
                request_id=request.id,
                ctx=ctx,
            )
            started = "onboarding started"
        else:
            started = "its onboarding continues"
        sourcing.onboarding_id = reused.id
        sourcing.status = SourcingStatus.AWAITING_VENDOR
        what = (
            f"Chose new vendor {name} for {request.reference} at {total} "
            f"{request.currency}; {started}"
        )
    record_event(
        session,
        "fpod.vendor_chosen",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        vendor=name,
        total=str(total),
        justification=justification or None,
        summary=what + (f". Justification: {justification}" if justification else ""),
    )
    await session.commit()


async def vendor_activated(session: AsyncSession, request_id: uuid.UUID, code: str) -> None:
    """Onboarding finished: the request's sourcing can go on to the PO."""
    sourcing = await session.scalar(select(FpSourcing).where(FpSourcing.request_id == request_id))
    if sourcing is not None and sourcing.status == SourcingStatus.AWAITING_VENDOR:
        sourcing.chosen_vendor_code = code
        sourcing.status = SourcingStatus.CHOSEN
