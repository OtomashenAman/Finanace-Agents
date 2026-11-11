"""Client account and credit set-up (AR Phase 1): the client's portal application, the
onboarding agent's checks, the credit agent's proposal, the credit controller's decision,
the account agent's set-up in the ERP and the lab system, and the monitor's reviews.

Guardrails:
- no credit without human approval: a client's limit, deposit and terms are set only by a
  credit controller's decision (on the application, or on a monitor's review)
- the person who opened the application can't approve its credit (unless self-approval is
  allowed, then marked)
- the account is created once, from the approved record, in both systems; the monitor
  puts the lab system back in line with the ERP when they drift
"""

import csv
import hashlib
import io
import re
import secrets
import statistics
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMProvider
from src.app.finance_pod import mail
from src.app.finance_pod.access import FinanceAccess, check_different_person
from src.app.finance_pod.clients import agents
from src.app.finance_pod.clients.lab import LabRecord, get_lab
from src.app.finance_pod.clients.models import (
    ApplicationStatus,
    ClientDocumentKind,
    ClientStatus,
    FpClient,
    FpClientApplication,
    FpClientDocument,
    FpClientHistory,
    FpCreditReview,
    ReviewStatus,
)
from src.app.finance_pod.clients.schemas import (
    ApplicationOut,
    ApplicationSummary,
    ClientOut,
    DecisionIn,
    DocumentOut,
    HistoryImport,
    MonitorResult,
    PortalView,
    ReviewDecisionIn,
    ReviewOut,
    SyncState,
)
from src.app.finance_pod.erp import ErpCustomer, get_erp
from src.app.finance_pod.settings.service import current

DOC_TYPES = {"application/pdf", "image/png", "image/jpeg"}
MAX_DOC_BYTES = 10 * 1024 * 1024
OPEN = (ApplicationStatus.INVITED, ApplicationStatus.NEEDS_INFO)


class ApplicationNotFoundError(AppError):
    status_code = 404
    code = "client_application_not_found"
    message = "Client application not found."


class ClientNotFoundError(AppError):
    status_code = 404
    code = "client_not_found"
    message = "Client not found."


class ClientStateError(AppError):
    status_code = 409
    code = "client_state"


class ClientInvalidError(AppError):
    status_code = 422
    code = "client_invalid"


class ClientPortalLinkError(AppError):
    status_code = 404
    code = "client_portal_link_invalid"
    message = "This link isn't valid any more. Ask your contact for a new one."


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def portal_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/client-portal/{token}"


def _money(value: Decimal | None, currency: str) -> str:
    return "—" if value is None else f"{currency} {value:,.2f}"


def _terms_text(limit: Decimal | None, deposit: Decimal, terms: str, currency: str) -> str:
    if limit is None:
        return f"deposit only ({mail.percent(deposit)} up front), {terms}"
    return f"credit limit {_money(limit, currency)} on {terms}" + (
        f", {mail.percent(deposit)} deposit" if deposit else ""
    )


# --- 1.1.1: the client's secure application ------------------------------------------------


async def _issue_link(
    session: AsyncSession,
    row: FpClientApplication,
    sent_by: uuid.UUID,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID | None,
    message: str | None = None,
) -> str:
    """A new single-use link by email: the first invitation, or the gaps to fix."""
    token = secrets.token_urlsafe(32)
    row.token_hash = _hash(token)
    row.token_expires_at = utcnow() + timedelta(days=get_settings().vendor_portal_days)
    row.invited_at = row.invited_at or utcnow()
    link = portal_url(token)
    org = get_settings().email_sender_name
    days = get_settings().vendor_portal_days
    if row.gaps or message:
        kind = mail.MailKind.CLIENT_GAPS
        subject = f"{org}: a few things to complete on your account application"
        listed = "\n".join(f"- {g}" for g in row.gaps)
        body = (
            f"Hello {row.client_name},\n\nThank you for your application. Before we can set "
            "up your account we need the following:\n\n"
            + (f"{listed}\n\n" if listed else "")
            + (f"{message}\n\n" if message else "")
            + f"Please use this secure link to update it (your earlier answers are kept):\n\n"
            f"{link}\n\nThe link works once and expires in {days} days.\n\nThank you,\n{org}"
        )
        event, what = "fpod.client_gaps_sent", "sent the client what's missing"
    else:
        kind = mail.MailKind.CLIENT_INVITE
        subject = f"{org}: open your client account"
        body = (
            f"Hello {row.client_name},\n\nTo open your account with us, please complete our "
            "secure application: your company and tax details, contacts, the credit terms "
            "you'd like, and upload your business registration and tax document. A recent "
            "credit report and trade references help us offer credit sooner.\n\n"
            f"{link}\n\nThe link works once and expires in {days} days.\n\nThank you,\n{org}"
        )
        event, what = "fpod.client_invited", "sent the secure application link"
    sent = await mail.send(
        session,
        kind=kind,
        to_email=row.client_email,
        to_name=row.client_name,
        subject=subject,
        body=body,
        sent_by=sent_by,
    )
    record_event(
        session,
        event,
        ctx,
        actor_id=actor_id,
        application_id=str(row.id),
        to=row.client_email,
        status=sent.status.value,
        summary=f"Onboarding agent {what} to {row.client_name} ({row.client_email})"
        + (f": {'; '.join(row.gaps)}" if row.gaps and kind == mail.MailKind.CLIENT_GAPS else "")
        + mail.outcome(sent),
    )
    return token


async def invite(
    session: AsyncSession, access: FinanceAccess, name: str, email: str, ctx: RequestContext
) -> tuple[FpClientApplication, str]:
    """Open an application and send the client its secure link; returns it with the token
    (shown once, never stored)."""
    row = FpClientApplication(
        status=ApplicationStatus.INVITED,
        client_name=name.strip(),
        client_email=email.lower(),
        invited_by=access.user.id,
    )
    session.add(row)
    await session.flush()
    token = await _issue_link(session, row, access.user.id, ctx, actor_id=access.user.id)
    await session.commit()
    return row, token


async def _load(
    session: AsyncSession, application_id: uuid.UUID, *, lock: bool = False
) -> FpClientApplication:
    row = await session.get(FpClientApplication, application_id, with_for_update=lock)
    if row is None:
        raise ApplicationNotFoundError
    return row


async def resend(
    session: AsyncSession, access: FinanceAccess, application_id: uuid.UUID, ctx: RequestContext
) -> str:
    row = await _load(session, application_id, lock=True)
    if row.status not in OPEN:
        raise ClientStateError("The client already sent the application; a new link isn't needed.")
    token = await _issue_link(session, row, access.user.id, ctx, actor_id=access.user.id)
    await session.commit()
    return token


async def request_info(
    session: AsyncSession,
    access: FinanceAccess,
    application_id: uuid.UUID,
    message: str,
    ctx: RequestContext,
) -> str:
    """Client services asks the client for more (with the agent's gaps, if any)."""
    row = await _load(session, application_id, lock=True)
    if row.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.PROPOSED):
        raise ClientStateError("Only a submitted application can go back to the client.")
    row.status, row.proposal, row.proposed_at = ApplicationStatus.NEEDS_INFO, None, None
    token = await _issue_link(
        session, row, access.user.id, ctx, actor_id=access.user.id, message=message.strip()
    )
    await session.commit()
    return token


async def _by_token(
    session: AsyncSession, token: str, *, lock: bool = False
) -> FpClientApplication:
    if not token or len(token) > 100:
        raise ClientPortalLinkError
    query = select(FpClientApplication).where(FpClientApplication.token_hash == _hash(token))
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ClientPortalLinkError
    return row


async def portal_view(session: AsyncSession, token: str) -> PortalView:
    row = await _by_token(session, token)
    expired = row.token_expires_at is not None and row.token_expires_at < utcnow()
    held = sorted({d.kind for d in await agents.latest_documents(session, row)})
    return PortalView(
        client_name=row.client_name,
        status="used" if row.status not in OPEN else "expired" if expired else "open",
        expires_at=row.token_expires_at,
        organisation=get_settings().email_sender_name,
        gaps=row.gaps if row.status == ApplicationStatus.NEEDS_INFO else [],
        documents_held=held,
        # The tax ID isn't sent back: a forwarded email shouldn't show it
        previous={
            k: getattr(row, k)
            for k in (
                "legal_name",
                "country",
                "address",
                "phone",
                "website",
                "billing_email",
                "contacts",
                "currency",
                "requested_limit",
                "requested_terms",
                "expected_monthly",
                "years_trading",
            )
        }
        if row.submissions
        else {},
    )


async def portal_submit(
    session: AsyncSession,
    token: str,
    fields: dict[str, Any],
    files: list[tuple[ClientDocumentKind, str, str, bytes]],
    llm: LLMProvider,
    ctx: RequestContext,
) -> None:
    """The client's application (1.1.1); the onboarding agent checks it at once (1.1.2)."""
    row = await _by_token(session, token, lock=True)
    if row.status not in OPEN:
        raise ClientPortalLinkError("This application was already sent. Thank you.")
    if row.token_expires_at and row.token_expires_at < utcnow():
        raise ClientPortalLinkError("This link has expired. Ask your contact for a new one.")
    if not fields["contacts"]:
        raise ClientInvalidError("Give at least one contact.")
    held = set(
        await session.scalars(
            select(FpClientDocument.sha256).where(FpClientDocument.application_id == row.id)
        )
    )
    for kind, filename, content_type, data in files:
        ct = content_type.split(";")[0].strip().lower()
        if ct not in DOC_TYPES:
            raise ClientInvalidError(f"{filename}: upload a PDF, PNG or JPEG.")
        if not data or len(data) > MAX_DOC_BYTES:
            raise ClientInvalidError(f"{filename}: empty or larger than 10 MB.")
        sha = hashlib.sha256(data).hexdigest()
        if sha not in held:
            held.add(sha)
            session.add(
                FpClientDocument(
                    application_id=row.id,
                    kind=kind,
                    filename=filename[:255],
                    content_type=ct,
                    size=len(data),
                    sha256=sha,
                    content=data,
                )
            )
    for key, value in fields.items():
        setattr(row, key, value)
    row.submissions += 1
    row.submitted_at = row.submitted_at or utcnow()
    row.token_hash = None  # single use
    row.cleared = []  # a fresh submission is checked afresh
    await session.flush()
    await agents.onboard(session, llm, row)
    row.agent_ran_at = utcnow()
    issues = agents.open_issues(row)
    if row.first_issues is None:
        row.first_issues = len(issues)
    record_event(
        session,
        "fpod.client_application_submitted",
        ctx,
        actor_id=None,
        application_id=str(row.id),
        submission=row.submissions,
        summary=f"{row.client_name} sent the account application"
        + (f" (submission {row.submissions})" if row.submissions > 1 else "")
        + "; onboarding agent checked it: "
        + (
            f"{len(row.gaps)} gap(s) for the client"
            if row.gaps
            else f"{len(issues)} item(s) for client services"
            if issues
            else "all checks passed"
        ),
    )
    if row.gaps:
        row.status = ApplicationStatus.NEEDS_INFO
        await _issue_link(session, row, row.invited_by, ctx, actor_id=None)
    else:
        row.status = ApplicationStatus.SUBMITTED
        if not issues:
            await _assess(session, row, ctx, actor_id=None)
    await session.commit()


# --- 1.1.2 / 1.2.1: client services and the credit agent -----------------------------------


async def _assess(
    session: AsyncSession,
    row: FpClientApplication,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID | None,
) -> None:
    """The credit agent proposes terms (1.2.1); the credit controller decides."""
    settings = await current(session)
    row.proposal = agents.assess(row, settings.max_new_client_limit)
    row.proposed_at = utcnow()
    row.status = ApplicationStatus.PROPOSED
    p = row.proposal
    record_event(
        session,
        "fpod.client_credit_proposed",
        ctx,
        actor_id=actor_id,
        application_id=str(row.id),
        score=p["score"],
        risk=p["risk"],
        summary=f"Credit agent scored {row.client_name} {p['score']}/100 ({p['risk']} risk) and "
        "proposed "
        + _terms_text(
            Decimal(p["credit_limit"]) if p["credit_limit"] else None,
            Decimal(p["deposit_pct"]),
            p["payment_terms"],
            p["currency"],
        )
        + "; waiting for the credit controller",
    )


async def recheck(
    session: AsyncSession,
    access: FinanceAccess,
    application_id: uuid.UUID,
    llm: LLMProvider,
    ctx: RequestContext,
) -> None:
    """The onboarding agent reads and checks again; with nothing left open, the credit agent
    proposes."""
    row = await _load(session, application_id, lock=True)
    if row.status not in (ApplicationStatus.SUBMITTED, ApplicationStatus.PROPOSED):
        raise ClientStateError("The agent re-checks only a submitted, undecided application.")
    await agents.onboard(session, llm, row)
    row.agent_ran_at = utcnow()
    record_event(
        session,
        "fpod.client_application_rechecked",
        ctx,
        actor_id=access.user.id,
        application_id=str(row.id),
        summary=f"Onboarding agent re-checked {row.client_name}'s application",
    )
    if agents.open_issues(row):
        row.status, row.proposal, row.proposed_at = ApplicationStatus.SUBMITTED, None, None
    else:
        await _assess(session, row, ctx, actor_id=access.user.id)
    await session.commit()


async def clear(
    session: AsyncSession,
    access: FinanceAccess,
    application_id: uuid.UUID,
    key: str,
    note: str,
    ctx: RequestContext,
) -> None:
    row = await _load(session, application_id, lock=True)
    if row.status != ApplicationStatus.SUBMITTED:
        raise ClientStateError("Only a submitted application's checks can be cleared.")
    check = next((c for c in row.checks or [] if c["key"] == key), None)
    if check is None or check["status"] == "pass":
        raise ClientInvalidError("There's nothing to clear for that check.")
    if not check.get("clearable"):
        raise ClientInvalidError(
            f"'{check['label']}' can't be cleared: ask the client for what's missing instead."
        )
    row.cleared = [
        *[c for c in row.cleared if c["key"] != key],
        {"key": key, "note": note.strip(), "by": access.user.full_name, "at": utcnow().isoformat()},
    ]
    record_event(
        session,
        "fpod.client_check_cleared",
        ctx,
        actor_id=access.user.id,
        application_id=str(row.id),
        check=key,
        note=note,
        summary=f"Cleared '{check['label']}' for {row.client_name}: {note}",
    )
    if not agents.open_issues(row):
        await _assess(session, row, ctx, actor_id=access.user.id)
    await session.commit()


# --- 1.2.2 / 1.3.1: the credit controller decides; the account agent sets up once ----------


def _work_status(client: FpClient) -> str:
    if client.status == ClientStatus.ON_HOLD:
        return "hold"
    return "deposit" if client.credit_limit is None else "credit"


def _lab_record(client: FpClient) -> LabRecord:
    return LabRecord(
        client_code=client.code,
        name=client.name,
        billing_email=client.billing_email,
        currency=client.currency,
        work_status=_work_status(client),
        credit_limit=client.credit_limit,
        deposit_pct=client.deposit_pct,
    )


async def push(session: AsyncSession, client: FpClient) -> None:
    """Write the approved record to the ERP and the lab system: one set-up, both systems."""
    client.erp_ref = await get_erp().upsert_customer(
        ErpCustomer(
            code=client.code,
            name=client.name,
            billing_email=client.billing_email,
            tax_id=client.tax_id,
            currency=client.currency,
            credit_limit=client.credit_limit,
            payment_terms=client.payment_terms,
            on_hold=client.status == ClientStatus.ON_HOLD,
        )
    )
    client.lab_ref = await get_lab().upsert_client(session, _lab_record(client))
    client.synced_at = utcnow()


async def sync_state(session: AsyncSession, client: FpClient) -> SyncState:
    """Does the lab system still hold what the ERP (the approved record) says?"""
    lab = await get_lab().read_client(session, client.code)
    if lab is None:
        return SyncState(in_sync=False, differences=["not in the lab system"])
    want = _lab_record(client)
    labels = {
        "name": "name",
        "billing_email": "billing email",
        "currency": "currency",
        "work_status": "work status",
        "credit_limit": "credit limit",
        "deposit_pct": "deposit %",
    }
    diffs = [
        f"{label}: ERP {getattr(want, f) if getattr(want, f) is not None else '—'}, lab "
        f"{getattr(lab, f) if getattr(lab, f) is not None else '—'}"
        for f, label in labels.items()
        if getattr(want, f) != getattr(lab, f)
    ]
    return SyncState(in_sync=not diffs, differences=diffs)


async def _next_code(session: AsyncSession) -> str:
    n = (await session.scalar(select(func.count()).select_from(FpClient)) or 0) + 1
    while await session.scalar(select(FpClient.id).where(FpClient.code == f"C-{n:05d}")):
        n += 1
    return f"C-{n:05d}"


def can_decide(row: FpClientApplication, viewer: User, self_approval: bool) -> str | None:
    if row.status != ApplicationStatus.PROPOSED:
        return "Waiting for the credit agent's proposal."
    if row.invited_by == viewer.id and not self_approval:
        return "You opened this application: another Finance Admin approves its credit."
    return None


async def decide(
    session: AsyncSession,
    access: FinanceAccess,
    application_id: uuid.UUID,
    body: DecisionIn,
    ctx: RequestContext,
) -> FpClient:
    """The credit controller approves terms (1.2.2); the account agent creates the account
    once, in the ERP and the lab system, and confirms it to the client (1.3.1)."""
    row = await _load(session, application_id, lock=True)
    if row.status != ApplicationStatus.PROPOSED or row.proposal is None:
        raise ClientStateError("Only an application with the credit agent's proposal is decided.")
    self_approval = await check_different_person(
        session,
        access.user,
        row.invited_by,
        "Whoever opened the application can't also approve the client's credit.",
    )
    if body.credit_limit is None and body.deposit_pct <= 0:
        raise ClientInvalidError("Give a credit limit, or a deposit for a deposit-only account.")
    p = row.proposal
    proposed = (
        Decimal(p["credit_limit"]) if p["credit_limit"] else None,
        Decimal(p["deposit_pct"]),
        p["payment_terms"],
        p["currency"],
    )
    decided = (body.credit_limit, body.deposit_pct, body.payment_terms.strip(), body.currency)
    changed = proposed != decided
    if changed and not body.note.strip():
        raise ClientInvalidError("Say why you changed the credit agent's proposal.")
    settings = await current(session)
    client = FpClient(
        code=await _next_code(session),
        status=ClientStatus.ACTIVE,
        name=row.legal_name or row.client_name,
        tax_id=row.tax_id,
        country=row.country,
        address=row.address,
        billing_email=row.billing_email or row.client_email,
        contacts=row.contacts,
        currency=body.currency,
        credit_limit=body.credit_limit,
        deposit_pct=body.deposit_pct,
        payment_terms=body.payment_terms.strip(),
        risk=p["risk"],
        approved_by=access.user.id,
        last_reviewed_at=utcnow(),
        next_review_on=utcnow().date() + timedelta(days=settings.credit_review_days),
    )
    session.add(client)
    await session.flush()
    await push(session, client)
    row.status, row.client_id = ApplicationStatus.ACTIVE, client.id
    row.decided_by, row.decided_at = access.user.id, utcnow()
    row.decision_note, row.changed_from_proposal = body.note.strip() or None, changed
    terms = _terms_text(
        client.credit_limit, client.deposit_pct, client.payment_terms, client.currency
    )
    record_event(
        session,
        "fpod.client_credit_approved",
        ctx,
        actor_id=access.user.id,
        application_id=str(row.id),
        client_code=client.code,
        changed_from_proposal=changed,
        self_approval=self_approval,
        summary=f"Credit controller approved {client.name}: {terms}"
        + (
            " (changed from the credit agent's proposal: " + body.note.strip() + ")"
            if changed
            else ""
        )
        + (" (opened by the same person: self-approval allowed)" if self_approval else ""),
    )
    org = get_settings().email_sender_name
    sent = await mail.send(
        session,
        kind=mail.MailKind.CLIENT_WELCOME,
        to_email=client.billing_email,
        to_name=client.name,
        subject=f"{org}: your client account {client.code} is open",
        body=(
            f"Hello {client.name},\n\nYour account with us is open.\n\n"
            f"Account number: {client.code}\nCurrency: {client.currency}\n"
            f"Terms: {terms}\n\nPlease quote your account number when you send samples or "
            f"place work with the lab.\n\nThank you,\n{org}"
        ),
        sent_by=access.user.id,
    )
    record_event(
        session,
        "fpod.client_account_created",
        ctx,
        actor_id=access.user.id,
        application_id=str(row.id),
        client_code=client.code,
        erp=get_erp().name,
        summary=f"Account agent created {client.code} {client.name} in the ERP ({client.erp_ref}) "
        f"and the lab system ({client.lab_ref}) and emailed the account details to "
        f"{client.billing_email}{mail.outcome(sent)}",
    )
    await session.commit()
    return client


async def reject(
    session: AsyncSession,
    access: FinanceAccess,
    application_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> None:
    row = await _load(session, application_id, lock=True)
    if row.status in (ApplicationStatus.ACTIVE, ApplicationStatus.REJECTED):
        raise ClientStateError(f"Already {row.status.value}.")
    row.status, row.rejected_reason, row.token_hash = ApplicationStatus.REJECTED, reason, None
    record_event(
        session,
        "fpod.client_application_rejected",
        ctx,
        actor_id=access.user.id,
        application_id=str(row.id),
        summary=f"Rejected {row.client_name}'s account application: {reason}",
    )
    await session.commit()


# --- reading ---------------------------------------------------------------------------------


async def _names(session: AsyncSession, *ids: uuid.UUID | None) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(wanted)))
    return dict(rows.all())


async def _client_code(session: AsyncSession, client_id: uuid.UUID | None) -> str | None:
    return (
        await session.scalar(select(FpClient.code).where(FpClient.id == client_id))
        if client_id
        else None
    )


async def _summary(session: AsyncSession, r: FpClientApplication) -> dict[str, Any]:
    return {
        "id": r.id,
        "reference": r.reference,
        "status": r.status,
        "client_name": r.client_name,
        "client_email": r.client_email,
        "invited_at": r.invited_at,
        "submitted_at": r.submitted_at,
        "open_issues": len(agents.open_issues(r)) if r.checks is not None else None,
        "risk": (r.proposal or {}).get("risk"),
        "client_code": await _client_code(session, r.client_id),
    }


async def applications(session: AsyncSession) -> list[ApplicationSummary]:
    rows = await session.scalars(
        select(FpClientApplication).order_by(FpClientApplication.created_at.desc())
    )
    return [ApplicationSummary(**await _summary(session, r)) for r in rows]


async def application(
    session: AsyncSession, application_id: uuid.UUID, viewer: User, token: str | None = None
) -> ApplicationOut:
    """`token`: the portal link's, right after it was issued (it isn't stored)."""
    r = await _load(session, application_id)
    names = await _names(session, r.decided_by, r.invited_by)
    docs = await session.scalars(
        select(FpClientDocument)
        .where(FpClientDocument.application_id == r.id)
        .order_by(FpClientDocument.created_at)
    )
    self_approval = (await current(session)).allow_self_approval
    return ApplicationOut(
        **await _summary(session, r),
        token_expires_at=r.token_expires_at,
        submissions=r.submissions,
        legal_name=r.legal_name,
        tax_id=r.tax_id,
        country=r.country,
        address=r.address,
        phone=r.phone,
        website=r.website,
        billing_email=r.billing_email,
        contacts=r.contacts,
        currency=r.currency,
        requested_limit=r.requested_limit,
        requested_terms=r.requested_terms,
        expected_monthly=r.expected_monthly,
        years_trading=r.years_trading,
        extraction=r.extraction,
        checks=r.checks or [],
        cleared=r.cleared,
        gaps=r.gaps,
        agent_ran_at=r.agent_ran_at,
        proposal=r.proposal,
        proposed_at=r.proposed_at,
        decided_by_name=names.get(r.decided_by) if r.decided_by else None,
        decided_at=r.decided_at,
        decision_note=r.decision_note,
        changed_from_proposal=r.changed_from_proposal,
        client_id=r.client_id,
        rejected_reason=r.rejected_reason,
        invited_by_name=names.get(r.invited_by),
        documents=[DocumentOut.model_validate(d, from_attributes=True) for d in docs],
        can_decide=can_decide(r, viewer, self_approval),
        portal_url=portal_url(token) if token else None,
    )


async def document(
    session: AsyncSession, application_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[str, str, bytes]:
    doc = await session.get(FpClientDocument, document_id)
    if doc is None or doc.application_id != application_id:
        raise ApplicationNotFoundError("Document not found.")
    content = await session.scalar(
        select(FpClientDocument.content).where(FpClientDocument.id == doc.id)
    )
    return doc.filename, doc.content_type, content or b""


async def _history(session: AsyncSession, code: str) -> agents.History:
    rows = list(
        await session.scalars(select(FpClientHistory).where(FpClientHistory.client_code == code))
    )
    return agents.history(rows, utcnow().date())


async def _client_out(session: AsyncSession, c: FpClient) -> ClientOut:
    names = await _names(session, c.approved_by)
    app_id = await session.scalar(
        select(FpClientApplication.id).where(FpClientApplication.client_id == c.id)
    )
    open_review = await session.scalar(
        select(FpCreditReview.id).where(
            FpCreditReview.client_id == c.id, FpCreditReview.status == ReviewStatus.PROPOSED
        )
    )
    return ClientOut(
        id=c.id,
        code=c.code,
        status=c.status,
        version=c.version,
        name=c.name,
        tax_id=c.tax_id,
        country=c.country,
        address=c.address,
        billing_email=c.billing_email,
        contacts=c.contacts,
        currency=c.currency,
        credit_limit=c.credit_limit,
        deposit_pct=c.deposit_pct,
        payment_terms=c.payment_terms,
        risk=c.risk,
        erp_ref=c.erp_ref,
        lab_ref=c.lab_ref,
        synced_at=c.synced_at,
        sync=await sync_state(session, c),
        last_reviewed_at=c.last_reviewed_at,
        next_review_on=c.next_review_on,
        approved_by_name=names.get(c.approved_by),
        application_id=app_id,
        history=(await _history(session, c.code)).as_dict(),
        open_review_id=open_review,
        created_at=c.created_at,
    )


async def clients(session: AsyncSession) -> list[ClientOut]:
    rows = await session.scalars(select(FpClient).order_by(FpClient.code))
    return [await _client_out(session, c) for c in rows]


async def _load_client(
    session: AsyncSession, client_id: uuid.UUID, *, lock: bool = False
) -> FpClient:
    c = await session.get(FpClient, client_id, with_for_update=lock)
    if c is None:
        raise ClientNotFoundError
    return c


async def client(session: AsyncSession, client_id: uuid.UUID) -> ClientOut:
    return await _client_out(session, await _load_client(session, client_id))


async def resync(
    session: AsyncSession, access: FinanceAccess, client_id: uuid.UUID, ctx: RequestContext
) -> ClientOut:
    c = await _load_client(session, client_id, lock=True)
    await _resync(session, c, ctx, actor_id=access.user.id)
    await session.commit()
    return await _client_out(session, c)


async def _resync(
    session: AsyncSession, c: FpClient, ctx: RequestContext, *, actor_id: uuid.UUID | None
) -> bool:
    """Put the lab system back in line with the ERP; True when something was corrected."""
    state = await sync_state(session, c)
    if state.in_sync:
        return False
    await push(session, c)
    c.sync_fixes += 1
    record_event(
        session,
        "fpod.client_resynced",
        ctx,
        actor_id=actor_id,
        client_code=c.code,
        differences=state.differences,
        summary=f"Account agent found the lab system out of line for {c.code} {c.name} and "
        f"corrected it from the ERP: {'; '.join(state.differences)}",
    )
    return True


# --- 1.3.2: the monitor ----------------------------------------------------------------------


async def run_monitor(
    session: AsyncSession, actor_id: uuid.UUID | None, ctx: RequestContext
) -> MonitorResult:
    """Review every account: put the lab system in line, and propose changes of terms as
    history builds or the periodic review falls due. The caller commits."""
    today = utcnow().date()
    reviewed = proposed = resynced = 0
    for c in list(await session.scalars(select(FpClient).with_for_update())):
        reviewed += 1
        if await _resync(session, c, ctx, actor_id=actor_id):
            resynced += 1
        waiting = await session.scalar(
            select(FpCreditReview.id).where(
                FpCreditReview.client_id == c.id, FpCreditReview.status == ReviewStatus.PROPOSED
            )
        )
        if waiting:
            continue
        h = await _history(session, c.code)
        found = agents.review(c, h, today)
        if found is None:
            continue
        trigger, terms, reasons = found
        review = FpCreditReview(
            client_id=c.id,
            status=ReviewStatus.PROPOSED,
            trigger=trigger,
            proposal={
                "metrics": h.as_dict(),
                "current": {
                    "status": c.status.value,
                    "credit_limit": str(c.credit_limit) if c.credit_limit is not None else None,
                    "deposit_pct": str(c.deposit_pct),
                    "payment_terms": c.payment_terms,
                },
                "proposed": terms,
                "reasons": reasons,
            },
        )
        session.add(review)
        await session.flush()
        proposed += 1
        record_event(
            session,
            "fpod.credit_review_proposed",
            ctx,
            actor_id=actor_id,
            client_code=c.code,
            review=review.reference,
            summary=f"Monitor proposed {review.reference} for {c.code} {c.name}: "
            + " ".join(reasons),
        )
    record_event(
        session,
        "fpod.client_monitor_ran",
        ctx,
        actor_id=actor_id,
        reviewed=reviewed,
        proposed=proposed,
        resynced=resynced,
        summary=f"Monitor reviewed {reviewed} client account(s): {proposed} change(s) proposed "
        f"for the credit controller, {resynced} lab record(s) corrected",
    )
    return MonitorResult(reviewed=reviewed, proposed=proposed, resynced=resynced)


async def _review_out(session: AsyncSession, r: FpCreditReview) -> ReviewOut:
    c = await session.get(FpClient, r.client_id)
    names = await _names(session, r.decided_by)
    return ReviewOut(
        id=r.id,
        reference=r.reference,
        client_id=r.client_id,
        client_code=c.code if c else "?",
        client_name=c.name if c else "?",
        currency=c.currency if c else "USD",
        status=r.status,
        trigger=r.trigger,
        proposal=r.proposal,
        decided_by_name=names.get(r.decided_by) if r.decided_by else None,
        decided_at=r.decided_at,
        decision_note=r.decision_note,
        created_at=r.created_at,
    )


async def reviews(session: AsyncSession, open_only: bool) -> list[ReviewOut]:
    query = select(FpCreditReview).order_by(FpCreditReview.created_at.desc())
    if open_only:
        query = query.where(FpCreditReview.status == ReviewStatus.PROPOSED)
    return [await _review_out(session, r) for r in await session.scalars(query)]


async def decide_review(
    session: AsyncSession,
    access: FinanceAccess,
    review_id: uuid.UUID,
    body: ReviewDecisionIn,
    ctx: RequestContext,
) -> ReviewOut:
    """The credit controller approves (as proposed or changed) or dismisses a review. Only an
    approval changes the client's terms, in both systems."""
    r = await session.get(FpCreditReview, review_id, with_for_update=True)
    if r is None:
        raise ClientNotFoundError("Review not found.")
    if r.status != ReviewStatus.PROPOSED:
        raise ClientStateError(f"Already {r.status.value}.")
    c = await _load_client(session, r.client_id, lock=True)
    r.decided_by, r.decided_at = access.user.id, utcnow()
    r.decision_note = body.note.strip() or None
    if not body.approve:
        r.status = ReviewStatus.DISMISSED
        record_event(
            session,
            "fpod.credit_review_dismissed",
            ctx,
            actor_id=access.user.id,
            client_code=c.code,
            review=r.reference,
            summary=f"Credit controller dismissed {r.reference} for {c.code} {c.name}"
            + (f": {r.decision_note}" if r.decision_note else ""),
        )
        await session.commit()
        return await _review_out(session, r)
    p = r.proposal["proposed"]
    if body.terms is not None:
        if not body.note.strip():
            raise ClientInvalidError("Say why you changed the monitor's proposal.")
        limit, deposit = body.terms.credit_limit, body.terms.deposit_pct
        terms, currency = body.terms.payment_terms.strip(), body.terms.currency
        status = ClientStatus(body.status or p["status"])
    else:
        limit = Decimal(p["credit_limit"]) if p["credit_limit"] else None
        deposit, terms, currency = Decimal(p["deposit_pct"]), p["payment_terms"], c.currency
        status = ClientStatus(p["status"])
    if limit is None and deposit <= 0 and status == ClientStatus.ACTIVE:
        raise ClientInvalidError("Give a credit limit, or a deposit for a deposit-only account.")
    before = _terms_text(c.credit_limit, c.deposit_pct, c.payment_terms, c.currency)
    c.credit_limit, c.deposit_pct, c.payment_terms = limit, deposit, terms
    c.currency, c.status = currency, status
    c.version += 1
    c.last_reviewed_at = utcnow()
    c.next_review_on = utcnow().date() + timedelta(days=(await current(session)).credit_review_days)
    await push(session, c)
    r.status = ReviewStatus.APPROVED
    after = _terms_text(c.credit_limit, c.deposit_pct, c.payment_terms, c.currency)
    record_event(
        session,
        "fpod.credit_review_approved",
        ctx,
        actor_id=access.user.id,
        client_code=c.code,
        review=r.reference,
        changed_from_proposal=body.terms is not None,
        summary=f"Credit controller approved {r.reference} for {c.code} {c.name}: "
        + (f"{before} → {after}" if before != after else f"terms confirmed ({after})")
        + (", on hold" if c.status == ClientStatus.ON_HOLD else "")
        + "; updated in the ERP and the lab system",
    )
    await session.commit()
    return await _review_out(session, r)


# --- history import (until later AR phases bill from here) ----------------------------------

COLUMNS = {
    "client": ("client", "client code", "account", "customer"),
    "invoice": ("invoice", "invoice number", "invoice no"),
    "amount": ("amount", "total"),
    "issued": ("issued", "invoice date", "date"),
    "due": ("due", "due date"),
    "paid": ("paid", "paid on", "paid date"),
}


def _cell_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _rows(data: bytes, filename: str) -> list[list[Any]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        return [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


async def import_history(
    session: AsyncSession, access: FinanceAccess, data: bytes, filename: str, ctx: RequestContext
) -> HistoryImport:
    """Invoices and payments per client (CSV or XLSX: Client, Invoice, Amount, Issued, Due,
    Paid); then the monitor reviews the accounts."""
    rows = _rows(data, filename)
    if not rows:
        raise ClientInvalidError("The file is empty.")
    header = [re.sub(r"\s+", " ", str(h or "").strip().lower()) for h in rows[0]]
    at: dict[str, int] = {}
    for key, names in COLUMNS.items():
        found = next((i for i, h in enumerate(header) if h in names), None)
        if found is None and key != "paid":
            raise ClientInvalidError(
                "Columns needed: Client, Invoice, Amount, Issued, Due (and Paid, blank if not "
                f"yet). Missing: {key}."
            )
        if found is not None:
            at[key] = found
    codes = set(await session.scalars(select(FpClient.code)))
    skipped: list[str] = []
    count, seen = 0, set()
    for n, raw in enumerate(rows[1:], start=2):
        if not any(v not in (None, "") for v in raw):
            continue
        cell = {k: raw[i] if i < len(raw) else None for k, i in at.items()}
        code = str(cell["client"] or "").strip()
        if code not in codes:
            skipped.append(f"row {n}: client {code or '(blank)'} isn't an account")
            continue
        try:
            amount = Decimal(str(cell["amount"]).replace(",", ""))
            issued, due = _cell_date(cell["issued"]), _cell_date(cell["due"])
            paid = _cell_date(cell.get("paid"))
        except (InvalidOperation, ValueError):
            skipped.append(f"row {n}: amount or a date can't be read (dates as YYYY-MM-DD)")
            continue
        if issued is None or due is None:
            skipped.append(f"row {n}: issued and due dates are needed")
            continue
        number = str(cell["invoice"] or "").strip()[:80]
        existing = await session.scalar(
            select(FpClientHistory).where(
                FpClientHistory.client_code == code, FpClientHistory.invoice_number == number
            )
        )
        row = existing or FpClientHistory(client_code=code, invoice_number=number)
        row.amount, row.issued_on, row.due_on, row.paid_on = amount, issued, due, paid
        if existing is None:
            session.add(row)
        count += 1
        seen.add(code)
    await session.flush()
    record_event(
        session,
        "fpod.client_history_imported",
        ctx,
        actor_id=access.user.id,
        rows=count,
        clients=len(seen),
        summary=f"Imported {count} invoice(s) of billing and payment history for "
        f"{len(seen)} client(s)" + (f"; skipped {len(skipped)}" if skipped else ""),
    )
    monitor = await run_monitor(session, access.user.id, ctx)
    await session.commit()
    return HistoryImport(rows=count, clients=len(seen), skipped=skipped[:50], monitor=monitor)


# --- measures and overview -------------------------------------------------------------------


def _days(a: datetime | None, b: datetime | None) -> float | None:
    return (b - a).total_seconds() / 86400 if a and b else None


async def measures(session: AsyncSession) -> dict[str, Any]:
    """Account set-up time and data errors."""
    apps = list(await session.scalars(select(FpClientApplication)))
    done = [a for a in apps if a.status == ApplicationStatus.ACTIVE]
    setup = [d for a in done if (d := _days(a.invited_at, a.decided_at)) is not None]
    decision = [d for a in done if (d := _days(a.submitted_at, a.decided_at)) is not None]
    sent = [a for a in apps if a.first_issues is not None]
    gaps_sent = await session.scalar(
        select(func.count())
        .select_from(mail.FpEmail)
        .where(mail.FpEmail.kind == mail.MailKind.CLIENT_GAPS)
    )
    fixes = await session.scalar(select(func.coalesce(func.sum(FpClient.sync_fixes), 0)))
    by_review = dict(
        (
            await session.execute(
                select(FpCreditReview.status, func.count()).group_by(FpCreditReview.status)
            )
        ).all()
    )
    return {
        "applications": len(apps),
        "accounts": await session.scalar(select(func.count()).select_from(FpClient)) or 0,
        "setup_days_median": round(statistics.median(setup), 1) if setup else None,
        "decision_days_median": round(statistics.median(decision), 1) if decision else None,
        "first_pass_clean": sum(1 for a in sent if a.first_issues == 0),
        "first_pass_judged": len(sent),
        "issues_caught": sum(a.first_issues or 0 for a in sent),
        "gaps_sent": gaps_sent or 0,
        "sync_fixes": int(fixes or 0),
        "controller_changes": sum(1 for a in done if a.changed_from_proposal),
        "reviews_open": by_review.get(ReviewStatus.PROPOSED, 0),
        "reviews_approved": by_review.get(ReviewStatus.APPROVED, 0),
        "reviews_dismissed": by_review.get(ReviewStatus.DISMISSED, 0),
    }


async def overview_counts(session: AsyncSession) -> tuple[dict[str, int], int]:
    by_status = {
        str(s): n
        for s, n in (
            await session.execute(
                select(FpClientApplication.status, func.count()).group_by(
                    FpClientApplication.status
                )
            )
        ).all()
    }
    reviews_open = await session.scalar(
        select(func.count())
        .select_from(FpCreditReview)
        .where(FpCreditReview.status == ReviewStatus.PROPOSED)
    )
    return by_status, reviews_open or 0
