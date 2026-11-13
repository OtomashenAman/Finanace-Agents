"""Purchase orders (Phase 1.6): the PO agent drafts, the buyer checks, approval above the
limit, then issue (ERP + email to the vendor) and the vendor's acknowledgement.

Guardrails: no PO without an approved request (checked here and by a database trigger);
the vendor must be active in the vendor master; the PO's lines must add up to the chosen
quote; above the limit (authority matrix, scope "po") someone other than the requester and
the drafter approves (unless self-approval is allowed, then marked).
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.finance_pod import mail
from src.app.finance_pod.access import (
    FinanceAccess,
    SeparationOfDutiesError,
    check_different_person,
    finance_pod_people,
)
from src.app.finance_pod.erp import ErpPoLine, ErpPurchaseOrder, get_erp
from src.app.finance_pod.orders.models import FpPoLine, FpPurchaseOrder, PoStatus
from src.app.finance_pod.orders.schemas import PoIssue, PoLineOut, PoOut, PoSummary, PoUpdate
from src.app.finance_pod.reference.models import (
    AuthorityScope,
    FpAuthorityTier,
    FpVendor,
    VendorStatus,
)
from src.app.finance_pod.requests.agent import Reference, price_checks
from src.app.finance_pod.requests.exceptions import (
    RequestInvalidError,
    RequestLockedError,
    RequestNotFoundError,
    StaleRequestError,
)
from src.app.finance_pod.requests.models import FpPurchaseRequest, RequestStatus
from src.app.finance_pod.sourcing.models import FpSourcing, SourcingStatus

CENT = Decimal("0.01")
EDITABLE = frozenset({PoStatus.DRAFT})


# --- the PO agent --------------------------------------------------------------------------


def issues(po: FpPurchaseOrder) -> list[PoIssue]:
    """What stops the PO going ahead (computed every time it's shown)."""
    found = []
    if not po.lines:
        found.append(PoIssue(message="The PO has no lines.", blocking=True))
    if po.quote_total is not None and po.total != po.quote_total:
        found.append(
            PoIssue(
                message=(
                    f"The lines add up to {po.total:,.2f} but the chosen quote is "
                    f"{po.quote_total:,.2f} {po.currency}: adjust the line prices."
                ),
                blocking=True,
            )
        )
    if not po.vendor_email:
        found.append(PoIssue(message="The vendor has no email to send the PO to.", blocking=True))
    if po.delivery_date and po.delivery_date < utcnow().date():
        found.append(PoIssue(message="The delivery date is in the past.", blocking=False))
    if not po.payment_terms:
        found.append(PoIssue(message="No payment terms.", blocking=False))
    return found


async def _approval_tier(
    session: AsyncSession, cost_centre: str | None, total: Decimal
) -> FpAuthorityTier | None:
    tiers = list(
        await session.scalars(
            select(FpAuthorityTier)
            .where(FpAuthorityTier.scope == AuthorityScope.PO)
            .order_by(FpAuthorityTier.min_amount)
        )
    )
    specific = [t for t in tiers if t.cost_centre_code == cost_centre]
    applicable = [
        t
        for t in (specific or [t for t in tiers if t.cost_centre_code is None])
        if t.min_amount <= total
    ]
    return applicable[-1] if applicable else None


async def _load_request(session: AsyncSession, request_id: uuid.UUID) -> FpPurchaseRequest:
    request = await session.get(FpPurchaseRequest, request_id, with_for_update=True)
    if request is None:
        raise RequestNotFoundError
    return request


async def draft(
    session: AsyncSession, access: FinanceAccess, request_id: uuid.UUID, ctx: RequestContext
) -> FpPurchaseOrder:
    """The PO agent drafts the PO from the approved request and the buyer's choice
    (1.6.1.a-b): lines, prices (contract, quote or estimate), coding and terms."""
    request = await _load_request(session, request_id)
    if request.status != RequestStatus.APPROVED:
        raise RequestLockedError("No PO without an approved request.")
    existing = await session.scalar(
        select(FpPurchaseOrder).where(
            FpPurchaseOrder.request_id == request.id,
            FpPurchaseOrder.status != PoStatus.CANCELLED,
        )
    )
    if existing is not None:
        raise RequestLockedError(f"{existing.reference} already exists for {request.reference}.")
    sourcing = await session.scalar(select(FpSourcing).where(FpSourcing.request_id == request.id))
    if sourcing is None or sourcing.status != SourcingStatus.CHOSEN:
        raise RequestLockedError(
            "Choose the vendor first"
            + (
                ": the new vendor is still being onboarded."
                if sourcing and sourcing.status == SourcingStatus.AWAITING_VENDOR
                else "."
            )
        )
    vendor = await session.scalar(
        select(FpVendor).where(FpVendor.code == sourcing.chosen_vendor_code)
    )
    if vendor is None or vendor.status != VendorStatus.APPROVED or not vendor.active:
        raise RequestLockedError("The chosen vendor isn't active in the vendor master.")

    ref = await Reference.load(session)
    contract = {
        c.line: c
        for c in price_checks(request, ref, utcnow().date())
        if c.vendor_code == vendor.code and c.contract_price is not None
    }
    quote_total = sourcing.chosen_total if sourcing.chosen_quote_id else None
    lines = []
    for n, ln in enumerate(request.lines, start=1):
        if n in contract:
            price, source = contract[n].contract_price, "contract"
        elif quote_total is not None and len(request.lines) == 1:
            price, source = (quote_total / ln.quantity).quantize(CENT), "quote"
        else:
            price, source = ln.unit_price or Decimal("0"), "estimate"
        assert price is not None  # noqa: S101 - contract matches carry a price
        lines.append(
            FpPoLine(
                position=n,
                description=ln.description,
                quantity=ln.quantity,
                unit=ln.unit,
                unit_price=price,
                category=ln.category,
                catalogue_item_code=contract[n].item_code if n in contract else None,
                price_source=source,
            )
        )
    po = FpPurchaseOrder(
        request_id=request.id,
        status=PoStatus.DRAFT,
        vendor_code=vendor.code,
        vendor_name=vendor.name,
        vendor_email=sourcing.chosen_vendor_email or vendor.email,
        currency=request.currency,
        payment_terms=sourcing.payment_terms,
        delivery_date=sourcing.delivery_date or request.needed_by,
        cost_centre_code=request.cost_centre_code,
        lab_code=request.lab_code,
        project_code=request.project_code,
        grant_code=request.grant_code,
        quote_total=quote_total,
        drafted_by=access.user.id,
        lines=lines,
    )
    session.add(po)
    await session.flush()
    record_event(
        session,
        "fpod.po_drafted",
        ctx,
        actor_id=access.user.id,
        run=request.reference,
        po=po.reference,
        summary=f"PO agent drafted {po.reference} for {request.reference}: {vendor.name}, "
        f"{po.total:,.2f} {po.currency}"
        + (
            "; the lines don't add up to the quote yet"
            if quote_total is not None and po.total != quote_total
            else ""
        ),
    )
    await session.commit()
    return po


# --- reading -------------------------------------------------------------------------------


async def _load(session: AsyncSession, po_id: uuid.UUID, *, lock: bool = False) -> FpPurchaseOrder:
    po = await session.get(FpPurchaseOrder, po_id, with_for_update=lock)
    if po is None:
        raise RequestNotFoundError("Purchase order not found.")
    return po


async def get(session: AsyncSession, po_id: uuid.UUID) -> FpPurchaseOrder:
    return await _load(session, po_id)


async def _can_approve(session: AsyncSession, po: FpPurchaseOrder, viewer: User) -> str | None:
    if po.status != PoStatus.PENDING_APPROVAL:
        return "Not waiting for approval."
    from src.app.finance_pod.settings.service import current

    named = await session.scalar(
        select(User.id).where(
            User.email.ilike(po.approver_email or ""),
            finance_pod_people(),
        )
    )
    if named is not None and named != viewer.id:
        return f"Waiting for {po.approver_email} ({po.approval_capacity})."
    self_ok = (await current(session)).allow_self_approval
    request = await session.get(FpPurchaseRequest, po.request_id)
    if not self_ok and request is not None and request.requester_id == viewer.id:
        return "You raised the request: a different Finance Admin approves its PO."
    if not self_ok and po.drafted_by == viewer.id:
        return "You drafted this PO: a different Finance Admin approves it."
    return None


async def out(session: AsyncSession, po: FpPurchaseOrder, viewer: User) -> PoOut:
    request = await session.get(FpPurchaseRequest, po.request_id)
    ids = {i for i in (po.drafted_by, po.approved_by) if i}
    names = dict(
        (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    )
    return PoOut(
        id=po.id,
        reference=po.reference,
        request_id=po.request_id,
        request_reference=request.reference if request else "",
        status=po.status,
        version=po.version,
        vendor_code=po.vendor_code,
        vendor_name=po.vendor_name,
        vendor_email=po.vendor_email,
        currency=po.currency,
        total=po.total,
        quote_total=po.quote_total,
        payment_terms=po.payment_terms,
        delivery_date=po.delivery_date,
        cost_centre_code=po.cost_centre_code,
        lab_code=po.lab_code,
        project_code=po.project_code,
        grant_code=po.grant_code,
        notes=po.notes,
        lines=[
            PoLineOut(
                description=ln.description,
                quantity=ln.quantity,
                unit=ln.unit,
                unit_price=ln.unit_price,
                category=ln.category,
                catalogue_item_code=ln.catalogue_item_code,
                price_source=ln.price_source,
                amount=ln.amount,
            )
            for ln in po.lines
        ],
        issues=issues(po)
        if po.status in (PoStatus.DRAFT, PoStatus.PENDING_APPROVAL, PoStatus.APPROVED)
        else [],
        drafted_by_name=names.get(po.drafted_by, "a deleted user"),
        approval_capacity=po.approval_capacity,
        approver_email=po.approver_email,
        approved_by_name=names.get(po.approved_by) if po.approved_by else None,
        approved_at=po.approved_at,
        approval_acting_for=po.approval_acting_for,
        self_approval=po.self_approval,
        issued_at=po.issued_at,
        erp_system=po.erp_system,
        erp_ref=po.erp_ref,
        acknowledged_at=po.acknowledged_at,
        acknowledgement_note=po.acknowledgement_note,
        acknowledgement_filename=po.acknowledgement_filename,
        cancelled_reason=po.cancelled_reason,
        created_at=po.created_at,
        can_approve=await _can_approve(session, po, viewer),
    )


async def for_request(session: AsyncSession, request_id: uuid.UUID) -> FpPurchaseOrder | None:
    """The request's live PO, else its latest cancelled one."""
    return await session.scalar(
        select(FpPurchaseOrder)
        .where(FpPurchaseOrder.request_id == request_id)
        .order_by((FpPurchaseOrder.status == PoStatus.CANCELLED), FpPurchaseOrder.created_at.desc())
        .limit(1)
    )


async def summaries(session: AsyncSession, status: PoStatus | None) -> list[PoSummary]:
    query = (
        select(FpPurchaseOrder, FpPurchaseRequest.number)
        .join(FpPurchaseRequest, FpPurchaseRequest.id == FpPurchaseOrder.request_id)
        .order_by(FpPurchaseOrder.number.desc())
    )
    if status is not None:
        query = query.where(FpPurchaseOrder.status == status)
    return [
        PoSummary(
            id=po.id,
            reference=po.reference,
            request_id=po.request_id,
            request_reference=f"PR-{number:04d}",
            status=po.status,
            vendor_name=po.vendor_name,
            total=po.total,
            currency=po.currency,
            issued_at=po.issued_at,
            created_at=po.created_at,
        )
        for po, number in (await session.execute(query)).all()
    ]


async def waiting_for(session: AsyncSession, viewer: User) -> list[uuid.UUID]:
    pending = await session.scalars(
        select(FpPurchaseOrder).where(FpPurchaseOrder.status == PoStatus.PENDING_APPROVAL)
    )
    return [po.id for po in pending if await _can_approve(session, po, viewer) is None]


# --- changing ------------------------------------------------------------------------------


def _check_version(po: FpPurchaseOrder, version: int) -> None:
    if po.version != version:
        raise StaleRequestError("Someone changed this PO since you opened it. Reload it.")


async def update(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    body: PoUpdate,
    ctx: RequestContext,
) -> FpPurchaseOrder:
    po = await _load(session, po_id, lock=True)
    _check_version(po, body.expected_version)
    if po.status not in EDITABLE:
        raise RequestLockedError(f"{po.reference} is {po.status.value}: it can't be edited.")
    # A line whose description and price stay keeps its source; anything else is the buyer's
    before = {ln.description: ln for ln in po.lines}
    new_lines = []
    for n, ln in enumerate(body.lines, start=1):
        old = before.get(ln.description.strip())
        same = old is not None and old.unit_price == ln.unit_price
        new_lines.append(
            FpPoLine(
                position=n,
                description=ln.description.strip(),
                quantity=ln.quantity,
                unit=ln.unit,
                unit_price=ln.unit_price,
                category=ln.category,
                price_source=old.price_source if same and old else "buyer",
                catalogue_item_code=old.catalogue_item_code if same and old else None,
            )
        )
    po.lines = new_lines
    po.payment_terms = body.payment_terms
    po.delivery_date = body.delivery_date
    po.notes = body.notes
    po.version += 1
    await session.flush()
    record_event(
        session,
        "fpod.po_edited",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        summary=f"Edited {po.reference}: {po.total:,.2f} {po.currency}",
    )
    await session.commit()
    return po


async def confirm(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    version: int,
    ctx: RequestContext,
) -> FpPurchaseOrder:
    """The buyer confirms the draft: above the limit it waits for approval (1.6.2.a)."""
    po = await _load(session, po_id, lock=True)
    _check_version(po, version)
    if po.status != PoStatus.DRAFT:
        raise RequestLockedError(f"{po.reference} is already {po.status.value}.")
    blocking = [i.message for i in issues(po) if i.blocking]
    if blocking:
        raise RequestInvalidError("Fix these first: " + " ".join(blocking))
    tier = await _approval_tier(session, po.cost_centre_code, po.total)
    if tier is not None:
        po.status = PoStatus.PENDING_APPROVAL
        po.approval_capacity, po.approver_email = tier.capacity, tier.approver_email
        what = f"waits for {tier.capacity} ({tier.approver_email}): above {tier.min_amount:,.2f}"
    else:
        po.status = PoStatus.APPROVED
        what = "within the buyer's limit, ready to issue"
    po.version += 1
    record_event(
        session,
        "fpod.po_confirmed",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        summary=f"Confirmed {po.reference} ({po.total:,.2f} {po.currency}): {what}",
    )
    await session.commit()
    return po


async def approve(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    version: int,
    ctx: RequestContext,
) -> FpPurchaseOrder:
    po = await _load(session, po_id, lock=True)
    _check_version(po, version)
    if po.status != PoStatus.PENDING_APPROVAL:
        raise RequestLockedError(f"{po.reference} isn't waiting for approval.")
    named = await session.scalar(
        select(User.id).where(
            User.email.ilike(po.approver_email or ""),
            finance_pod_people(),
        )
    )
    acting_for = None
    if named is not None:
        if named != access.user.id:
            raise SeparationOfDutiesError(
                f"This PO waits for {po.approver_email} ({po.approval_capacity})."
            )
    else:
        acting_for = po.approver_email
    request = await session.get(FpPurchaseRequest, po.request_id)
    assert request is not None  # noqa: S101 - RESTRICT foreign key
    self_approval = await check_different_person(
        session, access.user, request.requester_id, "Nobody approves the PO of their own request."
    )
    self_approval = (
        await check_different_person(
            session, access.user, po.drafted_by, "The buyer who drafted the PO can't approve it."
        )
        or self_approval
    )
    po.status = PoStatus.APPROVED
    po.approved_by, po.approved_at = access.user.id, utcnow()
    po.approval_acting_for, po.self_approval = acting_for, self_approval
    po.version += 1
    record_event(
        session,
        "fpod.po_approved",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        run=request.reference,
        acting_for=acting_for,
        self_approval=self_approval,
        summary=f"Approved {po.reference} as {po.approval_capacity}"
        + (f" for {acting_for}" if acting_for else "")
        + (" (self-approval allowed)" if self_approval else ""),
    )
    await session.commit()
    return po


def _po_email(po: FpPurchaseOrder, request: FpPurchaseRequest) -> tuple[str, str]:
    org = get_settings().email_sender_name
    lines = "\n".join(
        f"  {n}. {ln.description}: {ln.quantity.normalize():f} {ln.unit or ''} x "
        f"{ln.unit_price:,.2f} = {ln.amount:,.2f}"
        for n, ln in enumerate(po.lines, start=1)
    )
    delivery = po.delivery_date.strftime("%d %B %Y") if po.delivery_date else "to be agreed"
    body = (
        f"Hello {po.vendor_name},\n\nPlease supply the following under purchase order "
        f"{po.reference} (our request {request.reference}):\n\n{lines}\n\n"
        f"Total: {po.total:,.2f} {po.currency}\nDelivery by: {delivery}\n"
        f"Payment terms: {po.payment_terms or 'as agreed'}\n\n"
        f"Please quote {po.reference} on your invoice and reply to confirm you accept this "
        "order and the delivery date.\n\nFor your protection: we never change bank details "
        f"by email.\n\nThank you,\n{org}"
    )
    return f"Purchase order {po.reference} from {org}", body


async def issue(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    version: int,
    ctx: RequestContext,
) -> FpPurchaseOrder:
    """Create the PO in the ERP and send it to the vendor (1.6.1.c)."""
    po = await _load(session, po_id, lock=True)
    _check_version(po, version)
    if po.status != PoStatus.APPROVED:
        raise RequestLockedError(f"{po.reference} isn't approved for issue.")
    request = await _load_request(session, po.request_id)
    if request.status != RequestStatus.APPROVED:
        raise RequestLockedError("No PO without an approved request.")
    blocking = [i.message for i in issues(po) if i.blocking]
    if blocking:
        raise RequestInvalidError("Fix these first: " + " ".join(blocking))
    vendor = await session.scalar(select(FpVendor).where(FpVendor.code == po.vendor_code))
    if vendor is None or vendor.status != VendorStatus.APPROVED or not vendor.active:
        raise RequestLockedError(f"Vendor {po.vendor_code} isn't active any more.")
    erp = get_erp()
    po.erp_ref = await erp.create_po(
        ErpPurchaseOrder(
            number=po.reference,
            vendor_code=po.vendor_code,
            currency=po.currency,
            total=po.total,
            lines=[ErpPoLine(ln.description, ln.quantity, ln.unit_price) for ln in po.lines],
            coding={
                "cost_centre": po.cost_centre_code,
                "lab": po.lab_code,
                "project": po.project_code,
                "grant": po.grant_code,
            },
        )
    )
    po.erp_system = erp.name
    subject, body = _po_email(po, request)
    assert po.vendor_email  # noqa: S101 - a blocking issue otherwise
    sent = await mail.send(
        session,
        kind=mail.MailKind.PURCHASE_ORDER,
        to_email=po.vendor_email,
        to_name=po.vendor_name,
        subject=subject,
        body=body,
        sent_by=access.user.id,
        request_id=request.id,
    )
    if sent.status == mail.MailStatus.FAILED:
        raise RequestInvalidError(f"The email provider refused the PO: {sent.error}. Not issued.")
    po.status = PoStatus.ISSUED
    po.issued_by, po.issued_at = access.user.id, utcnow()
    po.version += 1
    request.status = RequestStatus.ORDERED
    request.version += 1
    record_event(
        session,
        "fpod.po_issued",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        run=request.reference,
        erp=erp.name,
        erp_ref=po.erp_ref,
        summary=f"PO agent issued {po.reference} to {po.vendor_name} ({po.vendor_email}): "
        f"{po.total:,.2f} {po.currency}, {erp.name} ERP ref {po.erp_ref}{mail.outcome(sent)}",
    )
    await session.commit()
    return po


async def acknowledge(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    version: int,
    note: str,
    received_on: date | None,
    file: tuple[str, str, bytes] | None,
    ctx: RequestContext,
) -> FpPurchaseOrder:
    """Log the vendor's acknowledgement (1.6.1.c)."""
    po = await _load(session, po_id, lock=True)
    _check_version(po, version)
    if po.status != PoStatus.ISSUED:
        raise RequestLockedError(f"{po.reference} isn't waiting for an acknowledgement.")
    po.status = PoStatus.ACKNOWLEDGED
    po.acknowledged_at = utcnow()
    po.acknowledgement_note = (
        (f"Received {received_on.isoformat()}. " if received_on else "") + note.strip()
    ).strip() or None
    if file is not None:
        po.acknowledgement_filename, po.acknowledgement_content_type, po.acknowledgement_file = file
    po.version += 1
    record_event(
        session,
        "fpod.po_acknowledged",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        summary=f"Logged {po.vendor_name}'s acknowledgement of "
        f"{po.reference}" + (f": {note.strip()}" if note.strip() else ""),
    )
    await session.commit()
    return po


async def cancel(
    session: AsyncSession,
    access: FinanceAccess,
    po_id: uuid.UUID,
    version: int,
    reason: str,
    ctx: RequestContext,
) -> FpPurchaseOrder:
    po = await _load(session, po_id, lock=True)
    _check_version(po, version)
    if po.status in (PoStatus.ISSUED, PoStatus.ACKNOWLEDGED, PoStatus.CANCELLED):
        raise RequestLockedError(
            f"{po.reference} is {po.status.value}: an issued PO is cancelled with the vendor "
            "and in the ERP, not here."
        )
    po.status, po.cancelled_reason = PoStatus.CANCELLED, reason.strip()
    po.version += 1
    record_event(
        session,
        "fpod.po_cancelled",
        ctx,
        actor_id=access.user.id,
        po=po.reference,
        summary=f"Cancelled {po.reference}: {reason.strip()}",
    )
    await session.commit()
    return po


async def acknowledgement_file(session: AsyncSession, po_id: uuid.UUID) -> tuple[str, str, bytes]:
    po = await _load(session, po_id)
    content = await session.scalar(
        select(FpPurchaseOrder.acknowledgement_file).where(FpPurchaseOrder.id == po.id)
    )
    if not content or not po.acknowledgement_filename:
        raise RequestNotFoundError("No acknowledgement file.")
    return po.acknowledgement_filename, po.acknowledgement_content_type or "", content
