"""Outbound email (draft -> sent), imported replies and supporting documents.

- Sending approves the exact message first: the approval hash binds subject, body,
  recipient, attachments, purpose and transport, and customer mail needs the checklist.
- A message is sent once: the idempotency key comes from the approval, and an unclear
  outcome becomes send_unknown to reconcile, never an automatic retry.
- Customer mail goes only to the verified contact imported with the source; internal mail
  only to the configured recipients.
- A reply is accepted only from the address the message went to, on a provable thread.
"""

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMProvider
from src.app.core.llm.factory import get_llm_provider
from src.app.jobs import queue
from src.app.service_pod.common.canonical import fingerprint
from src.app.service_pod.common.people import DELETED, name_of, names
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases import system
from src.app.service_pod.core.cases.access import load_case
from src.app.service_pod.core.cases.exceptions import CaseActionError, StaleVersionError
from src.app.service_pod.core.cases.models import LOCKED_STATUSES, PodCase
from src.app.service_pod.core.hooks import Composed, hooks_for
from src.app.service_pod.core.messaging import providers
from src.app.service_pod.core.messaging.inbound import ReplyInvalidError, normalize_id, parse_eml
from src.app.service_pod.core.messaging.models import (
    ArtifactChannel,
    ArtifactKind,
    ArtifactStatus,
    Audience,
    Direction,
    MessageStatus,
    PodArtifact,
    PodMessage,
)
from src.app.service_pod.core.messaging.schemas import (
    ArtifactOut,
    EmailStatus,
    MessageDraftIn,
    MessageOut,
    MessageReconcile,
    MessageSend,
    MessageUpdate,
    ReplyImport,
)
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.workflows import PodKey, keys_in

SEND_JOB = "pod.send_message"
EXTRACT_JOB = "pod.extract_reply"
CASE_CLOSED = "case_closed"  # a reply that came after the case closed: kept, not read into it
EDITABLE = frozenset({MessageStatus.DRAFT, MessageStatus.SEND_FAILED})
ARTIFACT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class MessageNotFoundError(AppError):
    status_code = 404
    code = "message_not_found"
    message = "Message not found."


class MessageRefusedError(AppError):
    status_code = 409
    code = "message_refused"


class ArtifactNotFoundError(AppError):
    status_code = 404
    code = "artifact_not_found"
    message = "Document not found."


class ArtifactInvalidError(AppError):
    status_code = 422
    code = "artifact_invalid"


# --- reading ---------------------------------------------------------------------------


async def _message_outs(session: AsyncSession, messages: list[PodMessage]) -> list[MessageOut]:
    people = await names(
        session, [*(m.approved_by for m in messages), *(m.created_by for m in messages)]
    )
    cases = await session.scalars(
        select(PodCase).where(PodCase.id.in_({m.case_id for m in messages}))
    )
    refs = {c.id: c.reference for c in cases}
    return [
        MessageOut(
            id=m.id,
            case_id=m.case_id,
            case_reference=refs.get(m.case_id, ""),
            direction=m.direction,
            audience=m.audience,
            purpose=m.purpose,
            status=m.status,
            version=m.version,
            to_email=m.to_email,
            to_name=m.to_name,
            from_email=m.from_email,
            subject=m.subject,
            body=m.body,
            artifact_ids=[uuid.UUID(a) for a in m.artifact_ids],
            fact_block=m.fact_block,
            approval_checks=m.approval_checks,
            extraction=m.extraction,
            extraction_status=m.extraction_status,
            approved_by=name_of(people, m.approved_by),
            approved_at=m.approved_at,
            provider=m.provider,
            sender=m.sender,
            simulated=m.simulated,
            provider_message_id=m.provider_message_id,
            sent_at=m.sent_at,
            error=m.error,
            internet_message_id=m.internet_message_id,
            in_reply_to_id=m.in_reply_to_id,
            thread_evidence=m.thread_evidence,
            received_at=m.received_at,
            created_by=name_of(people, m.created_by),
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in messages
    ]


async def messages_for_case(session: AsyncSession, case: PodCase) -> list[MessageOut]:
    rows = await session.scalars(
        select(PodMessage).where(PodMessage.case_id == case.id).order_by(PodMessage.created_at)
    )
    return await _message_outs(session, list(rows))


async def list_messages(session: AsyncSession, status: MessageStatus | None) -> list[MessageOut]:
    """The inbox: messages on every case, newest first."""
    query = (
        select(PodMessage)
        .join(PodCase, PodCase.id == PodMessage.case_id)
        .where(PodCase.workflow.in_(keys_in(PodKey.SERVICE)))  # the Service POD's inbox
        .order_by(PodMessage.updated_at.desc())
        .limit(300)
    )
    if status is not None:
        query = query.where(PodMessage.status == status)
    return await _message_outs(session, list(await session.scalars(query)))


async def _artifact_outs(session: AsyncSession, artifacts: list[PodArtifact]) -> list[ArtifactOut]:
    people = await names(
        session, [*(a.uploaded_by for a in artifacts), *(a.decided_by for a in artifacts)]
    )
    return [
        ArtifactOut(
            id=a.id,
            case_id=a.case_id,
            kind=a.kind,
            invoice_refs=a.invoice_refs,
            filename=a.filename,
            content_type=a.content_type,
            size=a.size,
            sha256=a.sha256,
            status=a.status,
            uploaded_by=(
                people.get(a.uploaded_by, DELETED) if a.uploaded_by else "the vendor (portal)"
            ),
            channel=a.channel,
            decided_by=name_of(people, a.decided_by),
            decided_at=a.decided_at,
            created_at=a.created_at,
        )
        for a in artifacts
    ]


async def artifacts_for_case(session: AsyncSession, case: PodCase) -> list[ArtifactOut]:
    rows = await session.scalars(
        select(PodArtifact).where(PodArtifact.case_id == case.id).order_by(PodArtifact.created_at)
    )
    return await _artifact_outs(session, list(rows))


async def email_status() -> EmailStatus:
    provider = providers.get_email_provider()
    problem = await provider.readiness()
    return EmailStatus(
        provider=provider.name,
        simulated=provider.simulated,
        sender=provider.sender,
        ready=problem is None,
        problem=problem,
        internal_recipients=get_settings().pod_internal_recipients,
        test_recipient=get_settings().email_test_recipient,
    )


# --- checks ----------------------------------------------------------------------------


def _require_open(case: PodCase) -> None:
    if case.status in LOCKED_STATUSES:
        raise CaseActionError(f"{case.reference} is {case.status.value}; it can't change any more.")


def _source_contacts(snapshot: PodSnapshot, case: PodCase) -> set[str]:
    """The case customer's email as the source states it."""
    selected = case.selection.get("customer_id")
    return {
        c.email.lower()
        for c in snapshots.document(snapshot).customers or []
        if c.email and (selected is None or c.id == selected)
    }


def _vendor_contacts(snapshot: PodSnapshot) -> set[str]:
    """Active vendors' verified emails as the source states them (Finance POD)."""
    return {
        v.email.lower()
        for v in snapshots.document(snapshot).vendors or []
        if v.email and v.status == "Active"
    }


# The only mail that may go to a typed address (the party isn't in the source yet): a portal
# invitation, or a client being told what's missing from their application
INVITE_PURPOSES = frozenset({"vendor_invite", "client_invite", "client_gaps"})


async def _check_recipient(
    session: AsyncSession, case: PodCase, audience: Audience, to_email: str, purpose: str = ""
) -> None:
    address = to_email.strip().lower()
    if audience == Audience.INVITE:
        # A new vendor isn't in the source yet: the invitation (a portal link, no figures)
        # is the only mail that may go to a typed address
        if purpose not in INVITE_PURPOSES:
            raise MessageRefusedError("Only a portal invitation goes to a typed address.")
        return
    if audience == Audience.VENDOR:
        snapshot = await session.get(PodSnapshot, case.snapshot_id)
        assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
        if address not in _vendor_contacts(snapshot):
            raise MessageRefusedError(
                "Vendor mail goes only to an active vendor's verified contact from the source."
            )
        return
    if audience == Audience.INTERNAL:
        allowed = {r.strip().lower() for r in get_settings().pod_internal_recipients}
        if address not in allowed:
            raise MessageRefusedError(
                "Internal reports go only to the configured internal recipients."
            )
        return
    snapshot = await session.get(PodSnapshot, case.snapshot_id)
    assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
    if snapshot.is_demo:
        return  # fictional customers: the demo recipient may be edited (see send_message)
    if address not in _source_contacts(snapshot, case):
        raise MessageRefusedError(
            "Customer mail goes only to the verified contact imported with the source data."
        )


async def _approved_artifacts(
    session: AsyncSession, case: PodCase, ids: list[uuid.UUID]
) -> list[PodArtifact]:
    if not ids:
        return []
    rows = list(await session.scalars(select(PodArtifact).where(PodArtifact.id.in_(ids))))
    if len(rows) != len(set(ids)) or any(a.case_id != case.id for a in rows):
        raise MessageRefusedError("Attachments must be documents of this case.")
    if any(a.status != ArtifactStatus.APPROVED for a in rows):
        raise MessageRefusedError("Only approved documents can be attached.")
    return rows


def _approval_hash(
    m: PodMessage, artifacts: list[PodArtifact], provider: str, sender: str | None
) -> str:
    return fingerprint(
        {
            "case": str(m.case_id),
            "audience": m.audience,
            "purpose": m.purpose,
            "to": m.to_email.lower(),
            "to_name": m.to_name,
            "subject": m.subject,
            "body": m.body,
            "artifacts": sorted([str(a.id), a.sha256] for a in artifacts),
            "facts": m.fact_block,
            "provider": provider,
            "sender": sender,
        }
    )


GENERIC_PURPOSE = "case_message"


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))


async def _facts_for(session: AsyncSession, case: PodCase, purpose: str) -> str | None:
    """The fact block a message of this purpose must carry; refuses unknown purposes and
    purposes that can't be drafted yet (e.g. an acknowledgement before verification)."""
    hooks = hooks_for(case.workflow)
    if purpose == GENERIC_PURPOSE:
        return None
    if purpose not in hooks.purposes:
        raise MessageRefusedError(f"{purpose!r} isn't a message this workflow sends.")
    if hooks.draft_blocker is not None:
        blocked = await hooks.draft_blocker(session, case, purpose)
        if blocked:
            raise MessageRefusedError(blocked)
    return await hooks.facts(session, case, purpose) if hooks.facts else None


def _require_facts(fact_block: str | None, body: str) -> None:
    if fact_block and _normalize(fact_block) not in _normalize(body):
        raise MessageRefusedError(
            "The verified figures from the source must stay in the message exactly as given."
        )


async def _load_message(
    session: AsyncSession, access: PodAccess, message_id: uuid.UUID, expected_version: int
) -> tuple[PodMessage, PodCase]:
    message = await session.get(PodMessage, message_id, with_for_update=True)
    if message is None:
        raise MessageNotFoundError
    case = await load_case(session, message.case_id, access=access)
    if message.version != expected_version:
        raise StaleVersionError("This message was changed by someone else. Refresh and retry.")
    return message, case


def _event(
    session: AsyncSession,
    event: str,
    ctx: RequestContext,
    actor: uuid.UUID | None,
    case: PodCase,
    message: PodMessage,
    summary: str,
    **details: Any,
) -> None:
    record_event(
        session,
        event,
        ctx,
        actor_id=actor,
        run=case.reference,
        case_id=str(case.id),
        message_id=str(message.id),
        summary=f"{case.reference}: {summary}",
        **details,
    )


# --- outbound --------------------------------------------------------------------------


async def add_draft(
    session: AsyncSession, case: PodCase, body: MessageDraftIn, user_id: uuid.UUID
) -> PodMessage:
    """A checked outbound draft (caller audits and commits); a workflow's agent drafts mail
    this way, and a person still approves and sends it."""
    _require_open(case)
    await _check_recipient(session, case, body.audience, body.to_email, body.purpose)
    await _approved_artifacts(session, case, body.artifact_ids)
    fact_block = await _facts_for(session, case, body.purpose)
    _require_facts(fact_block, body.body)
    message = PodMessage(
        case_id=case.id,
        direction=Direction.OUTBOUND,
        audience=body.audience,
        purpose=body.purpose,
        status=MessageStatus.DRAFT,
        to_email=str(body.to_email),
        to_name=body.to_name,
        subject=body.subject,
        body=body.body,
        artifact_ids=[str(a) for a in body.artifact_ids],
        fact_block=fact_block,
        internet_message_id=f"<{uuid.uuid4()}@finance-pod>",
        created_by=user_id,
    )
    session.add(message)
    await session.flush()
    return message


async def create_draft(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    body: MessageDraftIn,
    ctx: RequestContext,
) -> MessageOut:
    case = await load_case(session, case_id, access=access)
    message = await add_draft(session, case, body, access.user.id)
    _event(
        session,
        "pod.message_drafted",
        ctx,
        access.user.id,
        case,
        message,
        f"Drafted '{message.subject}' to {message.to_email}",
    )
    await session.commit()
    return (await _message_outs(session, [message]))[0]


async def update_message(
    session: AsyncSession,
    access: PodAccess,
    message_id: uuid.UUID,
    body: MessageUpdate,
    ctx: RequestContext,
) -> MessageOut:
    message, case = await _load_message(session, access, message_id, body.expected_version)
    _require_open(case)
    if message.direction != Direction.OUTBOUND or message.status not in EDITABLE:
        raise MessageRefusedError(f"A {message.status.value} message can't be edited.")
    if body.to_email is not None:
        message.to_email = str(body.to_email)
    if body.to_name is not None:
        message.to_name = body.to_name or None
    if body.subject is not None:
        message.subject = body.subject
    if body.body is not None:
        message.body = body.body
    if body.artifact_ids is not None:
        await _approved_artifacts(session, case, body.artifact_ids)
        message.artifact_ids = [str(a) for a in body.artifact_ids]
    assert message.audience is not None  # noqa: S101 - outbound messages have one
    await _check_recipient(session, case, message.audience, message.to_email, message.purpose)
    _require_facts(message.fact_block, message.body)
    message.status = MessageStatus.DRAFT  # an edit always needs a fresh approval
    message.approval_hash = message.approved_by = message.approved_at = None
    message.provider = message.sender = message.error = message.approval_checks = None
    message.version += 1
    _event(
        session,
        "pod.message_edited",
        ctx,
        access.user.id,
        case,
        message,
        "Edited a message",
    )
    await session.commit()
    return (await _message_outs(session, [message]))[0]


async def send_message(
    session: AsyncSession,
    access: PodAccess,
    message_id: uuid.UUID,
    body: MessageSend,
    ctx: RequestContext,
) -> MessageOut:
    """Approve the exact message (its hash binds subject, body, recipient, attachments,
    purpose and transport) and send it once."""
    message, case = await _load_message(session, access, message_id, body.expected_version)
    _require_open(case)
    if message.direction != Direction.OUTBOUND or message.status not in EDITABLE:
        raise MessageRefusedError(f"A {message.status.value} message can't be sent.")
    assert message.audience is not None  # noqa: S101
    if message.audience in (Audience.CUSTOMER, Audience.VENDOR) and not body.checks.all_confirmed:
        raise MessageRefusedError(
            "Confirm the recipient, the invoice mapping and the tone before sending."
        )
    await _check_recipient(session, case, message.audience, message.to_email, message.purpose)
    if message.fact_block is not None:
        # The case may have moved to a newer source since the draft: figures must be current
        if await _facts_for(session, case, message.purpose) != message.fact_block:
            raise MessageRefusedError(
                "The source figures changed since this draft: write it again from the case."
            )
        _require_facts(message.fact_block, message.body)
    artifacts = await _approved_artifacts(
        session, case, [uuid.UUID(a) for a in message.artifact_ids]
    )
    provider = providers.get_email_provider()
    problem = await provider.readiness()
    if problem is not None:
        raise MessageRefusedError(f"Email can't be sent yet: {problem}")
    if message.audience in (Audience.VENDOR, Audience.INVITE) and not provider.simulated:
        snapshot = await session.get(PodSnapshot, case.snapshot_id)
        assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
        if snapshot.is_demo and not get_settings().email_test_recipient:
            raise MessageRefusedError(
                "This case is on demo data: real mail from it goes only to a test address "
                "(EMAIL_TEST_RECIPIENT)."
            )
    if message.audience == Audience.CUSTOMER and not provider.simulated:
        snapshot = await session.get(PodSnapshot, case.snapshot_id)
        assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
        settings = get_settings()
        if snapshot.is_demo and not settings.email_test_recipient:
            if not settings.email_sandbox_to_quickbooks_contacts:
                raise MessageRefusedError(
                    "This case is on demo / sandbox data: real mail from it goes only to a test "
                    "address (EMAIL_TEST_RECIPIENT), or to the customer's own email from the "
                    "source with EMAIL_SANDBOX_TO_QUICKBOOKS_CONTACTS=true."
                )
            if message.to_email.lower() not in _source_contacts(snapshot, case):
                raise MessageRefusedError(
                    "On sandbox data, mail goes only to the customer's email as QuickBooks "
                    "states it, not to an edited address."
                )
    message.provider = provider.name
    message.sender = provider.sender
    message.approval_hash = _approval_hash(message, artifacts, provider.name, provider.sender)
    message.approved_by = access.user.id
    message.approved_at = utcnow()
    message.approval_checks = body.checks.model_dump()
    key = hashlib.sha256(f"{case.id}:{message.id}:{message.approval_hash}".encode()).hexdigest()
    message.idempotency_key = key
    message.status = MessageStatus.SENDING
    message.version += 1
    _event(
        session,
        "pod.message_send_requested",
        ctx,
        access.user.id,
        case,
        message,
        f"Approved and sent '{message.subject}' to {message.to_email} via {provider.name}",
        approval_hash=message.approval_hash,
    )
    job = await queue.enqueue(
        session, SEND_JOB, {"message_id": str(message.id)}, dedupe_key=key, max_attempts=1
    )
    await session.commit()
    await queue.dispatch(session, job, get_llm_provider())
    await session.refresh(message)
    return (await _message_outs(session, [message]))[0]


async def compose(
    session: AsyncSession,
    case_id: uuid.UUID,
    purpose: str,
    llm: LLMProvider,
) -> Composed:
    """A suggested draft for a workflow purpose: the source's figures plus wording. Nothing
    is saved; it is edited and saved as a draft."""
    case = await load_case(session, case_id)
    _require_open(case)
    compose_hook = hooks_for(case.workflow).compose
    if compose_hook is None or purpose == GENERIC_PURPOSE:
        raise MessageRefusedError("This workflow has no suggested draft for that purpose.")
    await _facts_for(session, case, purpose)  # unknown or blocked purposes are refused
    return await compose_hook(session, case, purpose, llm)


async def reconcile_message(
    session: AsyncSession,
    access: PodAccess,
    message_id: uuid.UUID,
    body: MessageReconcile,
    ctx: RequestContext,
) -> MessageOut:
    """Settle a send whose outcome was unknown, after checking the provider's own log."""
    message, case = await _load_message(session, access, message_id, body.expected_version)
    _require_open(case)
    if message.status != MessageStatus.SEND_UNKNOWN:
        raise MessageRefusedError("Only a send with an unknown outcome needs reconciling.")
    message.status = MessageStatus(body.outcome)
    if body.outcome == "sent":
        message.provider_message_id = body.provider_message_id or message.provider_message_id
        message.sent_at = message.sent_at or utcnow()
    message.error = f"Reconciled: {body.note}"[:500]
    message.version += 1
    _event(
        session,
        "pod.message_reconciled",
        ctx,
        access.user.id,
        case,
        message,
        f"Reconciled a send as {body.outcome.replace('_', ' ')}: {body.note}",
    )
    await session.commit()
    return (await _message_outs(session, [message]))[0]


# --- inbound ---------------------------------------------------------------------------


async def import_reply(
    session: AsyncSession,
    actor_id: uuid.UUID | None,
    case_id: uuid.UUID,
    body: ReplyImport,
    ctx: RequestContext,
    llm: LLMProvider,
) -> tuple[MessageOut, bool]:
    """(reply, created). Re-importing the same email returns the existing one. A workflow
    that reads replies gets it read in the background (see flows.extraction). actor_id None:
    read from the mailbox by the worker. A reply to a closed case is still kept (with
    extraction_status "case_closed") but not read into it: the case doesn't change."""
    case = await load_case(session, case_id, lock=True)
    closed = case.status in LOCKED_STATUSES
    sent = list(
        await session.scalars(
            select(PodMessage).where(
                PodMessage.case_id == case.id,
                PodMessage.direction == Direction.OUTBOUND,
                PodMessage.status == MessageStatus.SENT,
            )
        )
    )
    if body.raw_eml:
        parsed = parse_eml(body.raw_eml)
        from_email, subject, text = parsed.from_email, parsed.subject, parsed.body
        ids = set(parsed.replies_to)
        original = next(
            (
                m
                for m in sent
                if {normalize_id(x) for x in (m.internet_message_id, m.provider_message_id) if x}
                & ids
            ),
            None,
        )
        if original is None:
            raise ReplyInvalidError(
                "This email doesn't answer a message sent from this case (no matching "
                "In-Reply-To / References header)."
            )
        evidence, raw, message_id = "header", body.raw_eml, parsed.message_id
    else:
        assert body.from_email and body.body  # noqa: S101 - schema validated
        original = next((m for m in sent if m.id == body.reply_to_message_id), None)
        if original is None:
            raise ReplyInvalidError("Pick a message that was sent from this case.")
        from_email, subject, text = str(body.from_email).lower(), body.subject or "", body.body
        evidence, raw, message_id = "manual", body.body, None

    tester = (get_settings().email_test_recipient or "").lower()
    if from_email not in {original.to_email.lower(), tester}:
        raise ReplyInvalidError(
            f"The reply comes from {from_email}, but the message went to {original.to_email}."
        )
    content_sha = hashlib.sha256(f"{from_email}\n{subject}\n{text}".encode()).hexdigest()
    message_id = message_id or f"<pasted-{content_sha}@finance-pod>"
    existing = await session.scalar(
        select(PodMessage).where(
            PodMessage.case_id == case.id,
            PodMessage.direction == Direction.INBOUND,
            PodMessage.internet_message_id == message_id,
        )
    )
    if existing is not None:
        if existing.content_sha256 != content_sha:
            raise MessageRefusedError(
                "A different email with the same Message-ID was already imported."
            )
        return (await _message_outs(session, [existing]))[0], False

    reply = PodMessage(
        case_id=case.id,
        direction=Direction.INBOUND,
        purpose=original.purpose,
        status=MessageStatus.RECEIVED,
        to_email=original.sender or "",
        from_email=from_email,
        subject=subject[:300],
        body=text,
        artifact_ids=[],
        internet_message_id=message_id,
        in_reply_to_id=original.id,
        thread_evidence=evidence,
        content_sha256=content_sha,
        raw=raw,
        received_at=utcnow(),
        created_by=actor_id,
    )
    session.add(reply)
    await session.flush()
    _event(
        session,
        "pod.reply_imported",
        ctx,
        actor_id,
        case,
        reply,
        f"Imported a reply from {from_email} ({evidence} thread)"
        + (f", after the case was {case.status.value}" if closed else ""),
    )
    job = None
    if closed:
        reply.extraction_status = CASE_CLOSED
    elif hooks_for(case.workflow).extract_reply is not None:
        reply.extraction_status = "pending"
        job = await queue.enqueue(
            session,
            EXTRACT_JOB,
            {"message_id": str(reply.id)},
            dedupe_key=f"{EXTRACT_JOB}:{reply.id}",
        )
    await session.commit()
    await queue.dispatch(session, job, llm)
    await session.refresh(reply)
    return (await _message_outs(session, [reply]))[0], True


# --- artifacts -------------------------------------------------------------------------


async def upload_artifact(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    kind: ArtifactKind,
    invoice_refs: list[str],
    filename: str,
    content_type: str,
    data: bytes,
    ctx: RequestContext,
) -> ArtifactOut:
    case = await load_case(session, case_id, access=access)
    artifact = await add_artifact(
        session, case, kind, invoice_refs, filename, content_type, data, ctx,
        uploaded_by=access.user.id,
    )  # fmt: skip
    await session.commit()
    return (await _artifact_outs(session, [artifact]))[0]


async def add_artifact(
    session: AsyncSession,
    case: PodCase,
    kind: ArtifactKind,
    invoice_refs: list[str],
    filename: str,
    content_type: str,
    data: bytes,
    ctx: RequestContext,
    *,
    uploaded_by: uuid.UUID | None,
    channel: ArtifactChannel = ArtifactChannel.UPLOAD,
) -> PodArtifact:
    """A checked document on the case, audited (caller commits). uploaded_by None: the
    vendor, through the portal."""
    _require_open(case)
    content_type = content_type.split(";")[0].strip().lower()
    if content_type not in ARTIFACT_TYPES:
        raise ArtifactInvalidError("Allowed: PDF, PNG, JPEG, CSV, TXT, XLSX or DOCX.")
    if not data:
        raise ArtifactInvalidError("The file is empty.")
    snapshot = await session.get(PodSnapshot, case.snapshot_id)
    assert snapshot is not None  # noqa: S101
    known = {i.number for i in snapshots.document(snapshot).invoices or []}
    unknown = [r for r in invoice_refs if r not in known]
    if unknown:
        raise ArtifactInvalidError(f"Not invoices of this case's source: {', '.join(unknown)}.")
    sha256 = hashlib.sha256(data).hexdigest()
    duplicate = await session.scalar(
        select(PodArtifact.filename).where(
            PodArtifact.case_id == case.id, PodArtifact.sha256 == sha256
        )
    )
    if duplicate is not None:
        raise ArtifactInvalidError(f"This file is already attached as '{duplicate}'.")
    artifact = PodArtifact(
        case_id=case.id,
        kind=kind,
        invoice_refs=invoice_refs,
        filename=filename[:255],
        content_type=content_type,
        size=len(data),
        sha256=sha256,
        content=data,
        uploaded_by=uploaded_by,
        channel=channel,
    )
    session.add(artifact)
    await session.flush()
    who = "" if uploaded_by else " (the vendor, through the portal)"
    record_event(
        session,
        "pod.artifact_uploaded",
        ctx,
        actor_id=uploaded_by,
        run=case.reference,
        case_id=str(case.id),
        artifact_id=str(artifact.id),
        sha256=sha256,
        channel=channel.value,
        summary=f"{case.reference}: added {kind.value.replace('_', ' ')} {artifact.filename}{who}",
    )
    return artifact


async def decide_artifact(
    session: AsyncSession,
    access: PodAccess,
    artifact_id: uuid.UUID,
    decision: str,
    ctx: RequestContext,
) -> ArtifactOut:
    artifact = await session.get(PodArtifact, artifact_id, with_for_update=True)
    if artifact is None:
        raise ArtifactNotFoundError
    case = await load_case(session, artifact.case_id, access=access)
    _require_open(case)
    if artifact.status != ArtifactStatus.PENDING:
        raise ArtifactInvalidError("This document was already decided.")
    artifact.status = ArtifactStatus(decision)
    artifact.decided_by = access.user.id
    artifact.decided_at = utcnow()
    if artifact.status == ArtifactStatus.APPROVED:
        locked_case = await load_case(session, case.id, lock=True)
        settled = await system.satisfy_document_requests(
            session, locked_case, artifact.kind.value, artifact.invoice_refs, artifact.filename
        )
        if settled:
            system.bump_case(
                session,
                locked_case,
                "pod.case_documents_settled",
                f"{artifact.filename} settles {settled} document request(s)",
                actor_id=access.user.id,
                ctx=ctx,
            )
    record_event(
        session,
        "pod.artifact_decided",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        case_id=str(case.id),
        artifact_id=str(artifact.id),
        summary=f"{case.reference}: {decision} document {artifact.filename}",
    )
    await session.commit()
    return (await _artifact_outs(session, [artifact]))[0]


async def artifact_content(
    session: AsyncSession, artifact_id: uuid.UUID
) -> tuple[PodArtifact, bytes]:
    artifact = await session.get(PodArtifact, artifact_id)
    if artifact is None:
        raise ArtifactNotFoundError
    content = await session.scalar(select(PodArtifact.content).where(PodArtifact.id == artifact.id))
    return artifact, content or b""
