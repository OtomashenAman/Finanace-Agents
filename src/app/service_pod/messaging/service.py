"""Outbound email (draft -> approved -> sent), imported replies and supporting documents.

- The preparer drafts; a reviewer (not the author) approves the exact message. The approval
  hash binds subject, body, recipient, attachments, purpose and transport; any edit clears it.
- Sending is a separate action, once: the idempotency key comes from the approval, and an
  unclear outcome becomes send_unknown for a person to reconcile, never an automatic retry.
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
from src.app.core.llm.factory import get_llm_provider
from src.app.jobs import queue
from src.app.service_pod.access.service import PodAccess
from src.app.service_pod.canonical import fingerprint
from src.app.service_pod.cases.access import CaseRole, load_case, roles_on, visible_cases_clause
from src.app.service_pod.cases.exceptions import CaseActionError, StaleVersionError
from src.app.service_pod.cases.models import LOCKED_STATUSES, PodCase
from src.app.service_pod.messaging import providers
from src.app.service_pod.messaging.inbound import ReplyInvalidError, normalize_id, parse_eml
from src.app.service_pod.messaging.models import (
    ArtifactKind,
    ArtifactStatus,
    Audience,
    Direction,
    MessageStatus,
    PodArtifact,
    PodMessage,
)
from src.app.service_pod.messaging.schemas import (
    ArtifactOut,
    EmailStatus,
    MessageDraftIn,
    MessageOut,
    MessageReconcile,
    MessageUpdate,
    ReplyImport,
)
from src.app.service_pod.people import DELETED, name_of, names
from src.app.service_pod.snapshots import service as snapshots
from src.app.service_pod.snapshots.models import PodSnapshot

SEND_JOB = "pod.send_message"
EDITABLE = frozenset({MessageStatus.DRAFT, MessageStatus.APPROVED, MessageStatus.SEND_FAILED})
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
    return [
        MessageOut(
            id=m.id,
            case_id=m.case_id,
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
            created_by=people.get(m.created_by, DELETED),
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


async def list_messages(
    session: AsyncSession, access: PodAccess, status: MessageStatus | None
) -> list[MessageOut]:
    """The inbox: messages on every case the viewer works on, newest first."""
    query = (
        select(PodMessage)
        .join(PodCase, PodCase.id == PodMessage.case_id)
        .where(visible_cases_clause(access))
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
            uploaded_by=people.get(a.uploaded_by, DELETED),
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
    )


# --- checks ----------------------------------------------------------------------------


def _require(case: PodCase, access: PodAccess, *roles: CaseRole, to: str) -> None:
    if case.status in LOCKED_STATUSES:
        raise CaseActionError(f"{case.reference} is {case.status.value}; it can't change any more.")
    if not roles_on(case, access) & set(roles):
        raise CaseActionError(f"You can't {to} on {case.reference}.")


async def _check_recipient(
    session: AsyncSession, case: PodCase, audience: Audience, to_email: str
) -> None:
    address = to_email.strip().lower()
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
        return  # fictional customers: the demo recipient may be edited
    customers = snapshots.document(snapshot).customers or []
    selected = case.selection.get("customer_id")
    contacts = {
        (c.email or "").lower()
        for c in customers
        if c.email and (selected is None or c.id == selected)
    }
    if address not in contacts:
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
            "provider": provider,
            "sender": sender,
        }
    )


async def _load_message(
    session: AsyncSession, access: PodAccess, message_id: uuid.UUID, expected_version: int
) -> tuple[PodMessage, PodCase]:
    message = await session.get(PodMessage, message_id, with_for_update=True)
    if message is None:
        raise MessageNotFoundError
    case = await load_case(session, access, message.case_id)
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


async def create_draft(
    session: AsyncSession,
    access: PodAccess,
    case_id: uuid.UUID,
    body: MessageDraftIn,
    ctx: RequestContext,
) -> MessageOut:
    case = await load_case(session, access, case_id)
    _require(case, access, CaseRole.OWNER, to="draft messages")
    await _check_recipient(session, case, body.audience, body.to_email)
    await _approved_artifacts(session, case, body.artifact_ids)
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
        internet_message_id=f"<{uuid.uuid4()}@finance-pod>",
        created_by=access.user.id,
    )
    session.add(message)
    await session.flush()
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
    _require(case, access, CaseRole.OWNER, to="edit messages")
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
    await _check_recipient(session, case, message.audience, message.to_email)
    was_approved = message.status == MessageStatus.APPROVED
    message.status = MessageStatus.DRAFT  # an edit always needs a fresh approval
    message.approval_hash = message.approved_by = message.approved_at = None
    message.provider = message.sender = message.error = None
    message.version += 1
    _event(
        session,
        "pod.message_edited",
        ctx,
        access.user.id,
        case,
        message,
        "Edited a message" + (" (its approval was withdrawn)" if was_approved else ""),
    )
    await session.commit()
    return (await _message_outs(session, [message]))[0]


async def approve_message(
    session: AsyncSession,
    access: PodAccess,
    message_id: uuid.UUID,
    expected_version: int,
    ctx: RequestContext,
) -> MessageOut:
    message, case = await _load_message(session, access, message_id, expected_version)
    _require(case, access, CaseRole.REVIEWER, to="approve messages")
    if message.status != MessageStatus.DRAFT:
        raise MessageRefusedError("Only a draft can be approved.")
    if message.created_by == access.user.id:
        raise MessageRefusedError("Someone other than the author must approve a message.")
    assert message.audience is not None  # noqa: S101
    await _check_recipient(session, case, message.audience, message.to_email)
    artifacts = await _approved_artifacts(
        session, case, [uuid.UUID(a) for a in message.artifact_ids]
    )
    provider = providers.get_email_provider()
    problem = await provider.readiness()
    if problem is not None:
        raise MessageRefusedError(f"Email can't be sent yet: {problem}")
    message.provider = provider.name
    message.sender = provider.sender
    message.approval_hash = _approval_hash(message, artifacts, provider.name, provider.sender)
    message.approved_by = access.user.id
    message.approved_at = utcnow()
    message.status = MessageStatus.APPROVED
    message.version += 1
    _event(
        session,
        "pod.message_approved",
        ctx,
        access.user.id,
        case,
        message,
        f"Approved '{message.subject}' to {message.to_email} via {provider.name}",
        approval_hash=message.approval_hash,
    )
    await session.commit()
    return (await _message_outs(session, [message]))[0]


async def send_message(
    session: AsyncSession,
    access: PodAccess,
    message_id: uuid.UUID,
    expected_version: int,
    ctx: RequestContext,
) -> MessageOut:
    message, case = await _load_message(session, access, message_id, expected_version)
    _require(case, access, CaseRole.OWNER, CaseRole.REVIEWER, to="send messages")
    if message.status != MessageStatus.APPROVED or message.approval_hash is None:
        raise MessageRefusedError("Only an approved message can be sent.")
    artifacts = await _approved_artifacts(
        session, case, [uuid.UUID(a) for a in message.artifact_ids]
    )
    provider = providers.get_email_provider()
    if (provider.name, provider.sender) != (message.provider, message.sender):
        raise MessageRefusedError(
            "The email transport changed since approval: the message must be approved again."
        )
    if _approval_hash(message, artifacts, provider.name, provider.sender) != message.approval_hash:
        raise MessageRefusedError("The message no longer matches its approval.")
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
        f"Asked to send '{message.subject}'",
    )
    job = await queue.enqueue(
        session, SEND_JOB, {"message_id": str(message.id)}, dedupe_key=key, max_attempts=1
    )
    await session.commit()
    await queue.dispatch(session, job, get_llm_provider())
    await session.refresh(message)
    return (await _message_outs(session, [message]))[0]


async def reconcile_message(
    session: AsyncSession,
    access: PodAccess,
    message_id: uuid.UUID,
    body: MessageReconcile,
    ctx: RequestContext,
) -> MessageOut:
    """Settle a send whose outcome was unknown, after checking the provider's own log."""
    message, case = await _load_message(session, access, message_id, body.expected_version)
    _require(case, access, CaseRole.REVIEWER, to="reconcile sends")
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
    access: PodAccess,
    case_id: uuid.UUID,
    body: ReplyImport,
    ctx: RequestContext,
) -> tuple[MessageOut, bool]:
    """(reply, created). Re-importing the same email returns the existing one."""
    case = await load_case(session, access, case_id, lock=True)
    _require(case, access, CaseRole.OWNER, CaseRole.REVIEWER, to="import replies")
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

    if from_email != original.to_email.lower():
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
        created_by=access.user.id,
    )
    session.add(reply)
    await session.flush()
    _event(
        session,
        "pod.reply_imported",
        ctx,
        access.user.id,
        case,
        reply,
        f"Imported a reply from {from_email} ({evidence} thread)",
    )
    await session.commit()
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
    case = await load_case(session, access, case_id)
    _require(case, access, CaseRole.OWNER, to="add documents")
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
        uploaded_by=access.user.id,
    )
    session.add(artifact)
    await session.flush()
    record_event(
        session,
        "pod.artifact_uploaded",
        ctx,
        actor_id=access.user.id,
        run=case.reference,
        case_id=str(case.id),
        artifact_id=str(artifact.id),
        sha256=sha256,
        summary=f"{case.reference}: added {kind.value.replace('_', ' ')} {artifact.filename}",
    )
    await session.commit()
    return (await _artifact_outs(session, [artifact]))[0]


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
    case = await load_case(session, access, artifact.case_id)
    _require(case, access, CaseRole.REVIEWER, to="approve documents")
    if artifact.status != ArtifactStatus.PENDING:
        raise ArtifactInvalidError("This document was already decided.")
    if artifact.uploaded_by == access.user.id:
        raise ArtifactInvalidError("Someone other than the uploader must approve a document.")
    artifact.status = ArtifactStatus(decision)
    artifact.decided_by = access.user.id
    artifact.decided_at = utcnow()
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
    session: AsyncSession, access: PodAccess, artifact_id: uuid.UUID
) -> tuple[PodArtifact, bytes]:
    artifact = await session.get(PodArtifact, artifact_id)
    if artifact is None:
        raise ArtifactNotFoundError
    await load_case(session, access, artifact.case_id)  # visibility
    content = await session.scalar(select(PodArtifact.content).where(PodArtifact.id == artifact.id))
    return artifact, content or b""
