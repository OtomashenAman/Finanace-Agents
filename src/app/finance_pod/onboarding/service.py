"""Vendor onboarding (Phase 1.5): portal link, the agent's reading and checks, the AP
analyst's call-back, the second approver's activation.

Guardrails:
- bank details only arrive through the single-use portal link, never by email or a form an
  admin fills; they take effect only when a vendor is activated
- verification needs every check passed or cleared, and a call-back to a number from an
  independent source (never the one the vendor just sent)
- the person who verified can't activate (unless self-approval is allowed, then marked)
"""

import hashlib
import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMProvider
from src.app.data_sources import crypto
from src.app.finance_pod import mail
from src.app.finance_pod.access import FinanceAccess, check_different_person
from src.app.finance_pod.erp import ErpVendor, get_erp
from src.app.finance_pod.onboarding import agent
from src.app.finance_pod.onboarding.models import (
    DocumentKind,
    FpOnboarding,
    FpOnboardingDocument,
    FpVendorBankAccount,
    OnboardingKind,
    OnboardingStatus,
)
from src.app.finance_pod.onboarding.schemas import (
    CallbackIn,
    DocumentOut,
    OnboardingOut,
    OnboardingSummary,
    PortalView,
)
from src.app.finance_pod.reference.models import FpVendor, VendorStatus
from src.app.finance_pod.requests.models import FpPurchaseRequest

DOC_TYPES = {"application/pdf", "image/png", "image/jpeg"}
MAX_DOC_BYTES = 10 * 1024 * 1024


class OnboardingNotFoundError(AppError):
    status_code = 404
    code = "onboarding_not_found"
    message = "Onboarding not found."


class OnboardingStateError(AppError):
    status_code = 409
    code = "onboarding_state"


class OnboardingInvalidError(AppError):
    status_code = 422
    code = "onboarding_invalid"


class PortalLinkError(AppError):
    status_code = 404
    code = "portal_link_invalid"
    message = "This link isn't valid any more. Ask your contact for a new one."


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def portal_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/vendor-portal/{token}"


def _portal_email(row: FpOnboarding, link: str) -> tuple[str, str]:
    org = get_settings().email_sender_name
    what = (
        "update your bank details with us"
        if row.kind == OnboardingKind.BANK_CHANGE
        else "set you up as a supplier"
    )
    body = (
        f"Hello {row.vendor_name},\n\n"
        f"To {what}, please complete our secure vendor form and upload your tax form "
        "(W-9, or W-8 if you're outside the US) and a letter from your bank on its letterhead "
        f"confirming the account:\n\n{link}\n\n"
        f"The link works once and expires in {get_settings().vendor_portal_days} days.\n\n"
        "For your protection we never accept bank details by email, and we will call you on "
        "a number we already hold to confirm them before any payment.\n\n"
        f"Thank you,\n{org}"
    )
    return f"{org}: secure vendor form", body


async def _issue_link(
    session: AsyncSession, row: FpOnboarding, actor: User, ctx: RequestContext
) -> str:
    token = secrets.token_urlsafe(32)
    row.token_hash = _hash(token)
    row.token_expires_at = utcnow() + timedelta(days=get_settings().vendor_portal_days)
    row.invited_at = utcnow()
    link = portal_url(token)
    subject, body = _portal_email(row, link)
    sent = await mail.send(
        session,
        kind=mail.MailKind.PORTAL_INVITE,
        to_email=row.vendor_email,
        to_name=row.vendor_name,
        subject=subject,
        body=body,
        sent_by=actor.id,
        request_id=row.request_id,
    )
    record_event(
        session,
        "fpod.onboarding_invited",
        ctx,
        actor_id=actor.id,
        onboarding_id=str(row.id),
        to=row.vendor_email,
        status=sent.status.value,
        summary=f"Onboarding agent sent the secure portal link to {row.vendor_name} "
        f"({row.vendor_email}){mail.outcome(sent)}",
    )
    return token


async def invite(
    session: AsyncSession,
    access: FinanceAccess,
    *,
    vendor_name: str,
    vendor_email: str,
    request_id: uuid.UUID | None,
    ctx: RequestContext,
    kind: OnboardingKind = OnboardingKind.NEW_VENDOR,
    vendor_code: str | None = None,
) -> tuple[FpOnboarding, str]:
    """Start onboarding and send the portal link (1.5.1.a); returns it with the link's
    token (shown once, never stored). The caller commits."""
    row = FpOnboarding(
        kind=kind,
        status=OnboardingStatus.INVITED,
        vendor_name=vendor_name.strip(),
        vendor_email=vendor_email.lower(),
        vendor_code=vendor_code,
        request_id=request_id,
        invited_by=access.user.id,
    )
    session.add(row)
    await session.flush()
    return row, await _issue_link(session, row, access.user, ctx)


async def bank_change(
    session: AsyncSession,
    access: FinanceAccess,
    vendor_code: str,
    email: str | None,
    ctx: RequestContext,
) -> tuple[FpOnboarding, str]:
    """New bank details for an existing vendor: only through the portal, with the same
    checks, call-back and second approver as a new vendor."""
    vendor = await session.scalar(select(FpVendor).where(FpVendor.code == vendor_code))
    if vendor is None:
        raise OnboardingNotFoundError(f"Vendor {vendor_code} isn't in the vendor master.")
    to = email or vendor.email
    if not to:
        raise OnboardingInvalidError("The vendor has no email: give one for the portal link.")
    result = await invite(
        session,
        access,
        vendor_name=vendor.name,
        vendor_email=to,
        request_id=None,
        ctx=ctx,
        kind=OnboardingKind.BANK_CHANGE,
        vendor_code=vendor.code,
    )
    await session.commit()
    return result


async def _load(
    session: AsyncSession, onboarding_id: uuid.UUID, *, lock: bool = False
) -> FpOnboarding:
    row = await session.get(FpOnboarding, onboarding_id, with_for_update=lock)
    if row is None:
        raise OnboardingNotFoundError
    return row


async def resend(
    session: AsyncSession, access: FinanceAccess, onboarding_id: uuid.UUID, ctx: RequestContext
) -> str:
    """A new portal link (the old one stops working); returns its token."""
    row = await _load(session, onboarding_id, lock=True)
    if row.status != OnboardingStatus.INVITED:
        raise OnboardingStateError("The vendor already submitted; a new link isn't needed.")
    token = await _issue_link(session, row, access.user, ctx)
    await session.commit()
    return token


async def request_resubmission(
    session: AsyncSession,
    access: FinanceAccess,
    onboarding_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> str:
    """The submission doesn't hold up (wrong tax ID, documents that don't match): the vendor
    gets a new link and fills the form again. What they sent is discarded (the audit trail
    keeps the record); returns the new link's token."""
    row = await _load(session, onboarding_id, lock=True)
    if row.status != OnboardingStatus.SUBMITTED:
        raise OnboardingStateError("Only a submitted, unverified vendor can be asked to resubmit.")
    await session.execute(
        delete(FpOnboardingDocument).where(FpOnboardingDocument.onboarding_id == row.id)
    )
    for field in (
        "legal_name",
        "tax_id",
        "tax_form",
        "address",
        "phone",
        "bank_name",
        "account_name",
        "routing_number_enc",
        "account_number_enc",
        "account_last4",
        "extraction",
        "checks",
        "agent_ran_at",
        "submitted_at",
    ):
        setattr(row, field, None)
    row.cleared = []
    row.status = OnboardingStatus.INVITED
    record_event(
        session,
        "fpod.onboarding_resubmission_requested",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        reason=reason,
        summary=f"Asked {row.vendor_name} to submit the vendor form again: {reason}",
    )
    token = await _issue_link(session, row, access.user, ctx)
    await session.commit()
    return token


async def reuse_or_retire(
    session: AsyncSession,
    access: FinanceAccess,
    onboarding_id: uuid.UUID | None,
    email: str | None,
    ctx: RequestContext,
) -> FpOnboarding | None:
    """The buyer chose again. An open onboarding of the same vendor (email) is kept and
    returned; any other open one is retired (rejected as replaced). The caller commits."""
    if onboarding_id is None:
        return None
    row = await session.get(FpOnboarding, onboarding_id, with_for_update=True)
    if row is None or row.status in (OnboardingStatus.ACTIVE, OnboardingStatus.REJECTED):
        return None
    if email is not None and row.vendor_email == email.lower():
        return row
    row.status, row.token_hash = OnboardingStatus.REJECTED, None
    row.rejected_reason = "Replaced: the buyer chose another vendor."
    record_event(
        session,
        "fpod.onboarding_rejected",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        summary=f"Retired {row.vendor_name}'s onboarding: the buyer chose another vendor",
    )
    return None


# --- the vendor's side (no login: the token is the key) -----------------------------------


async def _by_token(session: AsyncSession, token: str, *, lock: bool = False) -> FpOnboarding:
    if not token or len(token) > 100:
        raise PortalLinkError
    query = select(FpOnboarding).where(FpOnboarding.token_hash == _hash(token))
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise PortalLinkError
    return row


async def portal_view(session: AsyncSession, token: str) -> PortalView:
    row = await _by_token(session, token)
    expired = row.token_expires_at is not None and row.token_expires_at < utcnow()
    status = "used" if row.status != OnboardingStatus.INVITED else "expired" if expired else "open"
    return PortalView(
        vendor_name=row.vendor_name,
        kind=row.kind,
        status=status,
        expires_at=row.token_expires_at,
        organisation=get_settings().email_sender_name,
    )


async def portal_submit(
    session: AsyncSession,
    token: str,
    *,
    legal_name: str,
    tax_id: str,
    tax_form: str,
    address: str,
    phone: str,
    bank_name: str,
    account_name: str,
    routing_number: str,
    account_number: str,
    files: list[tuple[DocumentKind, str, str, bytes]],
    llm: LLMProvider,
    ctx: RequestContext,
) -> None:
    row = await _by_token(session, token, lock=True)
    if row.status != OnboardingStatus.INVITED:
        raise PortalLinkError("This form was already submitted. Thank you.")
    if row.token_expires_at and row.token_expires_at < utcnow():
        raise PortalLinkError("This link has expired. Ask your contact for a new one.")
    if tax_form not in ("W-9", "W-8BEN", "W-8BEN-E"):
        raise OnboardingInvalidError("Choose the tax form: W-9, W-8BEN or W-8BEN-E.")
    routing = re.sub(r"[\s-]", "", routing_number)
    account = re.sub(r"[\s-]", "", account_number)
    if not re.fullmatch(r"[A-Za-z0-9]{4,34}", account) or not re.fullmatch(
        r"[A-Za-z0-9]{4,15}", routing
    ):
        raise OnboardingInvalidError("Check the account and routing numbers.")
    kinds = {k for k, *_ in files}
    if DocumentKind.TAX_FORM not in kinds or DocumentKind.BANK_LETTER not in kinds:
        raise OnboardingInvalidError("Upload both the tax form and the bank letter.")
    seen: set[str] = set()
    for kind, filename, content_type, data in files:
        ct = content_type.split(";")[0].strip().lower()
        if ct not in DOC_TYPES:
            raise OnboardingInvalidError(f"{filename}: upload a PDF, PNG or JPEG.")
        if not data or len(data) > MAX_DOC_BYTES:
            raise OnboardingInvalidError(f"{filename}: empty or larger than 10 MB.")
        sha = hashlib.sha256(data).hexdigest()
        if sha not in seen:
            seen.add(sha)
            session.add(
                FpOnboardingDocument(
                    onboarding_id=row.id,
                    kind=kind,
                    filename=filename[:255],
                    content_type=ct,
                    size=len(data),
                    sha256=sha,
                    content=data,
                )
            )
    row.legal_name = legal_name.strip()[:200]
    row.tax_id = tax_id.strip()[:40]
    row.tax_form = tax_form
    row.address = address.strip()[:2000]
    row.phone = phone.strip()[:40] or None
    row.bank_name = bank_name.strip()[:200]
    row.account_name = account_name.strip()[:200]
    row.routing_number_enc = crypto.encrypt(routing)
    row.account_number_enc = crypto.encrypt(account)
    row.account_last4 = account[-4:]
    row.status = OnboardingStatus.SUBMITTED
    row.submitted_at = utcnow()
    row.token_hash = None  # single use
    await session.flush()
    await agent.run(session, llm, row)
    row.agent_ran_at = utcnow()
    issues = agent.open_issues(row)
    record_event(
        session,
        "fpod.onboarding_submitted",
        ctx,
        actor_id=None,
        onboarding_id=str(row.id),
        summary=f"{row.vendor_name} submitted the vendor form; onboarding agent checked it: "
        + (f"{len(issues)} item(s) for the AP analyst" if issues else "all checks passed"),
    )
    await session.commit()


# --- the AP analyst and the second approver --------------------------------------------------


def _mask(enc: str | None) -> str | None:
    if not enc:
        return None
    value = crypto.decrypt(enc)
    return "•" * max(0, len(value) - 4) + value[-4:]


async def _names(session: AsyncSession, *ids: uuid.UUID | None) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
    return dict(rows.all())


async def _can_activate(session: AsyncSession, row: FpOnboarding, viewer: User) -> str | None:
    if row.status != OnboardingStatus.VERIFIED:
        return "Not verified yet."
    if row.verified_by == viewer.id:
        from src.app.finance_pod.settings.service import current

        if not (await current(session)).allow_self_approval:
            return "You verified this vendor: a second Finance Admin activates it."
    return None


def _can_verify(row: FpOnboarding) -> str | None:
    if row.status == OnboardingStatus.INVITED:
        return "Waiting for the vendor's form."
    if row.status != OnboardingStatus.SUBMITTED:
        return f"Already {row.status.value}."
    issues = agent.open_issues(row)
    if issues:
        return f"{len(issues)} check(s) to resolve first: " + "; ".join(c["label"] for c in issues)
    return None


async def _reference(session: AsyncSession, request_id: uuid.UUID | None) -> str | None:
    if request_id is None:
        return None
    req = await session.get(FpPurchaseRequest, request_id)
    return req.reference if req else None


async def summaries(session: AsyncSession) -> list[OnboardingSummary]:
    rows = await session.scalars(select(FpOnboarding).order_by(FpOnboarding.created_at.desc()))
    out = []
    for r in rows:
        out.append(
            OnboardingSummary(
                id=r.id,
                kind=r.kind,
                status=r.status,
                vendor_name=r.vendor_name,
                vendor_email=r.vendor_email,
                vendor_code=r.vendor_code,
                request_id=r.request_id,
                request_reference=await _reference(session, r.request_id),
                invited_at=r.invited_at,
                submitted_at=r.submitted_at,
                open_issues=len(agent.open_issues(r)) if r.checks is not None else None,
            )
        )
    return out


async def detail(
    session: AsyncSession, onboarding_id: uuid.UUID, viewer: User, token: str | None = None
) -> OnboardingOut:
    """`token`: the portal link's, right after it was issued (it isn't stored)."""
    r = await _load(session, onboarding_id)
    names = await _names(session, r.verified_by, r.activated_by)
    docs = await session.scalars(
        select(FpOnboardingDocument)
        .where(FpOnboardingDocument.onboarding_id == r.id)
        .order_by(FpOnboardingDocument.created_at)
    )
    return OnboardingOut(
        id=r.id,
        kind=r.kind,
        status=r.status,
        vendor_name=r.vendor_name,
        vendor_email=r.vendor_email,
        vendor_code=r.vendor_code,
        request_id=r.request_id,
        request_reference=await _reference(session, r.request_id),
        invited_at=r.invited_at,
        submitted_at=r.submitted_at,
        open_issues=len(agent.open_issues(r)) if r.checks is not None else None,
        token_expires_at=r.token_expires_at,
        legal_name=r.legal_name,
        tax_id=r.tax_id,
        tax_form=r.tax_form,
        address=r.address,
        phone=r.phone,
        bank_name=r.bank_name,
        account_name=r.account_name,
        routing_masked=_mask(r.routing_number_enc),
        account_masked=_mask(r.account_number_enc),
        extraction=r.extraction,
        checks=r.checks or [],
        cleared=r.cleared,
        agent_ran_at=r.agent_ran_at,
        callback_phone=r.callback_phone,
        callback_source=r.callback_source,
        callback_contact=r.callback_contact,
        callback_notes=r.callback_notes,
        verified_by_name=names.get(r.verified_by) if r.verified_by else None,
        verified_at=r.verified_at,
        activated_by_name=names.get(r.activated_by) if r.activated_by else None,
        activated_at=r.activated_at,
        erp_ref=r.erp_ref,
        rejected_reason=r.rejected_reason,
        documents=[DocumentOut.model_validate(d, from_attributes=True) for d in docs],
        can_verify=_can_verify(r),
        can_activate=await _can_activate(session, r, viewer),
        portal_url=portal_url(token) if token else None,
    )


async def document(
    session: AsyncSession, onboarding_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[str, str, bytes]:
    doc = await session.get(FpOnboardingDocument, document_id)
    if doc is None or doc.onboarding_id != onboarding_id:
        raise OnboardingNotFoundError("Document not found.")
    content = await session.scalar(
        select(FpOnboardingDocument.content).where(FpOnboardingDocument.id == doc.id)
    )
    return doc.filename, doc.content_type, content or b""


async def rerun_agent(
    session: AsyncSession,
    access: FinanceAccess,
    onboarding_id: uuid.UUID,
    llm: LLMProvider,
    ctx: RequestContext,
) -> None:
    row = await _load(session, onboarding_id, lock=True)
    if row.status != OnboardingStatus.SUBMITTED:
        raise OnboardingStateError("The agent re-checks only a submitted, unverified vendor.")
    await agent.run(session, llm, row)
    row.agent_ran_at = utcnow()
    record_event(
        session,
        "fpod.onboarding_rechecked",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        summary=f"Onboarding agent re-checked {row.vendor_name}",
    )
    await session.commit()


async def clear(
    session: AsyncSession,
    access: FinanceAccess,
    onboarding_id: uuid.UUID,
    key: str,
    note: str,
    ctx: RequestContext,
) -> None:
    row = await _load(session, onboarding_id, lock=True)
    if row.status != OnboardingStatus.SUBMITTED:
        raise OnboardingStateError("Only a submitted, unverified vendor's checks can be cleared.")
    check = next((c for c in row.checks or [] if c["key"] == key), None)
    if check is None or check["status"] == "pass":
        raise OnboardingInvalidError("There's nothing to clear for that check.")
    if not check.get("clearable"):
        raise OnboardingInvalidError(
            f"'{check['label']}' can't be cleared: the details disagree. Ask the vendor to "
            "resubmit (or reject the submission)."
        )
    row.cleared = [
        *[c for c in row.cleared if c["key"] != key],
        {"key": key, "note": note.strip(), "by": access.user.full_name, "at": utcnow().isoformat()},
    ]
    record_event(
        session,
        "fpod.onboarding_check_cleared",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        check=key,
        note=note,
        summary=f"Cleared '{check['label']}' for {row.vendor_name}: {note}",
    )
    await session.commit()


async def verify(
    session: AsyncSession,
    access: FinanceAccess,
    onboarding_id: uuid.UUID,
    body: CallbackIn,
    ctx: RequestContext,
) -> None:
    """The AP analyst called the vendor back and confirmed the bank details (1.5.2.a)."""
    row = await _load(session, onboarding_id, lock=True)
    if row.status != OnboardingStatus.SUBMITTED:
        raise OnboardingStateError("Only a submitted vendor can be verified.")
    blocker = _can_verify(row)
    if blocker:
        raise OnboardingInvalidError(blocker)
    if row.phone and re.sub(r"\D", "", body.phone) == re.sub(r"\D", "", row.phone):
        raise OnboardingInvalidError(
            "That's the phone number the vendor just gave: call a number from an independent "
            "source (records, official website, directory)."
        )
    if body.confirmed_last4 != row.account_last4:
        raise OnboardingInvalidError(
            "The account the vendor confirmed on the call doesn't match the form: don't "
            "verify; reject it or send a new link."
        )
    row.callback_phone, row.callback_source = body.phone.strip(), body.source
    row.callback_contact, row.callback_notes = body.contact.strip(), body.notes.strip() or None
    row.verified_by, row.verified_at = access.user.id, utcnow()
    row.status = OnboardingStatus.VERIFIED
    record_event(
        session,
        "fpod.onboarding_verified",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        callback_source=body.source,
        summary=f"Called {row.vendor_name} back on {body.phone} ({body.source}); "
        f"{body.contact} confirmed the account ending {body.confirmed_last4}",
    )
    await session.commit()


async def _next_vendor_code(session: AsyncSession) -> str:
    n = (await session.scalar(select(func.count()).select_from(FpVendor)) or 0) + 1
    while await session.scalar(select(FpVendor.id).where(FpVendor.code == f"V-{n:05d}")):
        n += 1
    return f"V-{n:05d}"


async def activate(
    session: AsyncSession, access: FinanceAccess, onboarding_id: uuid.UUID, ctx: RequestContext
) -> None:
    """The second approver activates the vendor (1.5.2.b): vendor master + bank account in
    force, in the ERP; a request waiting for this vendor goes on to its PO."""
    from src.app.finance_pod.sourcing import service as sourcing

    row = await _load(session, onboarding_id, lock=True)
    if row.status != OnboardingStatus.VERIFIED:
        raise OnboardingStateError("Only a verified vendor can be activated.")
    self_approval = await check_different_person(
        session,
        access.user,
        row.verified_by,
        "The person who verified the bank details can't also activate the vendor.",
    )
    assert row.routing_number_enc and row.account_number_enc and row.account_last4  # noqa: S101
    if row.kind == OnboardingKind.BANK_CHANGE:
        vendor = await session.scalar(select(FpVendor).where(FpVendor.code == row.vendor_code))
        if vendor is None:
            raise OnboardingStateError(f"Vendor {row.vendor_code} no longer exists.")
    else:
        vendor = FpVendor(
            code=await _next_vendor_code(session),
            name=row.legal_name or row.vendor_name,
            email=row.vendor_email,
            tax_id=row.tax_id,
            status=VendorStatus.APPROVED,
            categories=[],
        )
    erp = get_erp()
    row.erp_ref = await erp.create_vendor(
        ErpVendor(code=vendor.code, name=vendor.name, email=vendor.email, tax_id=vendor.tax_id)
    )
    if row.kind == OnboardingKind.NEW_VENDOR:
        session.add(vendor)
    await session.execute(
        update(FpVendorBankAccount)
        .where(
            FpVendorBankAccount.vendor_code == vendor.code, FpVendorBankAccount.retired_at.is_(None)
        )
        .values(retired_at=utcnow())
    )
    session.add(
        FpVendorBankAccount(
            vendor_code=vendor.code,
            onboarding_id=row.id,
            bank_name=row.bank_name or "",
            account_name=row.account_name or "",
            routing_number_enc=row.routing_number_enc,
            account_number_enc=row.account_number_enc,
            account_last4=row.account_last4,
        )
    )
    row.vendor_code = vendor.code
    row.activated_by, row.activated_at = access.user.id, utcnow()
    row.status = OnboardingStatus.ACTIVE
    if row.request_id:
        await sourcing.vendor_activated(session, row.request_id, vendor.code)
        # What it was chosen for, so the sourcing agent finds it for similar requests
        request = await session.get(FpPurchaseRequest, row.request_id)
        found = {ln.category for ln in request.lines if ln.category} if request else set()
        if found - set(vendor.categories):
            vendor.categories = sorted(set(vendor.categories) | found)
    record_event(
        session,
        "fpod.vendor_activated",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        vendor_code=vendor.code,
        erp=erp.name,
        self_approval=self_approval,
        summary=(
            f"Activated vendor {vendor.code} {vendor.name}"
            if row.kind == OnboardingKind.NEW_VENDOR
            else f"Activated new bank details for {vendor.code} {vendor.name}"
        )
        + f" (account ending {row.account_last4}, {erp.name} ERP)"
        + (" (verified by the same person: self-approval allowed)" if self_approval else ""),
    )
    await session.commit()


async def reject(
    session: AsyncSession,
    access: FinanceAccess,
    onboarding_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> None:
    row = await _load(session, onboarding_id, lock=True)
    if row.status in (OnboardingStatus.ACTIVE, OnboardingStatus.REJECTED):
        raise OnboardingStateError(f"Already {row.status.value}.")
    row.status, row.rejected_reason, row.token_hash = OnboardingStatus.REJECTED, reason, None
    record_event(
        session,
        "fpod.onboarding_rejected",
        ctx,
        actor_id=access.user.id,
        onboarding_id=str(row.id),
        summary=f"Rejected {row.vendor_name}'s onboarding: {reason}",
    )
    await session.commit()
