"""E-signature: upload a template, send it through PandaDoc, follow it to signed.

Every query is scoped to the signed-in person: their templates, the documents *they* sent.
Statuses arrive by PandaDoc's webhook (signed with the shared key) or a manual refresh.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.esign import field_tags, pandadoc
from src.app.esign.exceptions import (
    DocumentNotFoundError,
    DocumentNotSendableError,
    PandaDocError,
    SendRejectedError,
    TemplateNotFoundError,
    TemplateRejectedError,
    TemplateTooLargeError,
    WebhookNotConfiguredError,
    WebhookRejectedError,
)
from src.app.esign.models import EsignDocument, EsignEvent, EsignTemplate
from src.app.esign.schemas import (
    STATUS_LABELS,
    DocumentDetail,
    DocumentOut,
    DocumentPage,
    EsignReport,
    EsignSetup,
    EventOut,
    RecipientOut,
    SendRequest,
    SignatureLayout,
    SigningSession,
    Stage,
    StageCount,
    TemplateOut,
    TemplateUsage,
    label_of,
    stage_of,
)

log = logging.getLogger("finance_acc.esign")

# PandaDoc prepares an uploaded file in ~3-5 s; wait this long before leaving the send to
# the webhook (document.draft) or a retry
POLL_SECONDS = 1.5
POLL_ATTEMPTS = 12

_KINDS = {
    b"%PDF": ("application/pdf", ".pdf"),
    b"PK\x03\x04": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    b"{\\rtf": ("application/rtf", ".rtf"),
}
TERMINAL = frozenset(
    {
        "document.completed",
        "document.declined",
        "document.rejected",
        "document.voided",
        "document.expired",
        "document.paid",
        "failed",
    }
)


def setup() -> EsignSetup:
    settings = get_settings()
    return EsignSetup(
        configured=settings.pandadoc_api_key is not None,
        webhook_configured=settings.pandadoc_webhook_key is not None,
        webhook_url=f"{settings.public_base_url.rstrip('/')}/api/v1/esign/webhook",
        max_bytes=settings.upload_max_bytes,
        default_layout=default_layout(),
    )


def default_layout() -> SignatureLayout:
    settings = get_settings()
    return SignatureLayout(
        page=settings.pandadoc_signature_page,
        x=settings.pandadoc_signature_x,
        y=settings.pandadoc_signature_y,
        width=settings.pandadoc_signature_width,
        height=settings.pandadoc_signature_height,
    )


# Space between one signer's box and the next one's, below it
BOX_GAP = 20


def signer_boxes(layout: dict[str, Any], count: int) -> list[dict[str, float]]:
    """The template's box for the first signer; each further signer's box below it."""
    step = float(layout["height"]) + BOX_GAP
    return [{**layout, "y": float(layout["y"]) + i * step} for i in range(count)]


# --- templates ----------------------------------------------------------------------------


def _kind(data: bytes, filename: str) -> tuple[str, str]:
    for magic, kind in _KINDS.items():
        if data.startswith(magic):
            if kind[1] == ".docx" and not filename.lower().endswith(".docx"):
                break  # any zip starts with PK: only take a .docx
            return kind
    raise TemplateRejectedError()


async def upload_template(
    session: AsyncSession,
    user: User,
    name: str,
    description: str | None,
    filename: str,
    data: bytes,
    layout: SignatureLayout | None,
    ctx: RequestContext,
) -> TemplateOut:
    """`layout`: where the signature box goes; None when the file has field tags."""
    limit = get_settings().upload_max_bytes
    if len(data) > limit:
        raise TemplateTooLargeError(f"Templates can be at most {limit // (1024 * 1024)} MB.")
    if not data:
        raise TemplateRejectedError("The file is empty.")
    content_type, extension = _kind(data, filename)
    tags = field_tags.find_tags(field_tags.read_text(data, content_type))
    if issues := field_tags.problems(tags):
        raise TemplateRejectedError(" ".join(issues))
    if any(t.type == "signature" for t in tags):
        layout = None  # the file says where signers sign
    clean = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or f"template{extension}"
    template = EsignTemplate(
        owner_id=user.id,
        name=name.strip()[:200] or clean,
        description=(description or "").strip() or None,
        filename=clean[:255],
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        signature_layout=layout.model_dump() if layout else None,
        field_tags=[t.as_dict() for t in tags],
        data=data,
    )
    session.add(template)
    await session.flush()
    record_event(
        session,
        "esign.template_uploaded",
        ctx,
        actor_id=user.id,
        template_id=str(template.id),
        summary=f"Uploaded e-signature template {template.name}",
    )
    await session.commit()
    return _template_out(template)


def _template_out(template: EsignTemplate, times_sent: int = 0) -> TemplateOut:
    return TemplateOut.model_validate(
        {
            **{k: getattr(template, k) for k in _TEMPLATE_COLUMNS},
            "signers_needed": field_tags.signers_needed(template.field_tags),
            "times_sent": times_sent,
        }
    )


_TEMPLATE_COLUMNS = (
    "id",
    "name",
    "description",
    "filename",
    "content_type",
    "size_bytes",
    "signature_layout",
    "field_tags",
    "created_at",
)


async def _template(session: AsyncSession, user: User, template_id: uuid.UUID) -> EsignTemplate:
    template = await session.get(EsignTemplate, template_id, options=[undefer(EsignTemplate.data)])
    if template is None or template.owner_id != user.id:
        raise TemplateNotFoundError()
    return template


async def list_templates(session: AsyncSession, user: User) -> list[TemplateOut]:
    sent = (
        select(EsignDocument.template_id, func.count().label("n"))
        .where(EsignDocument.sender_id == user.id)
        .group_by(EsignDocument.template_id)
        .subquery()
    )
    rows = await session.execute(
        select(EsignTemplate, func.coalesce(sent.c.n, 0))
        .outerjoin(sent, sent.c.template_id == EsignTemplate.id)
        .where(EsignTemplate.owner_id == user.id)
        .order_by(EsignTemplate.created_at.desc())
    )
    return [_template_out(t, int(n)) for t, n in rows]


async def template_file(
    session: AsyncSession, user: User, template_id: uuid.UUID
) -> tuple[str, str, bytes]:
    template = await _template(session, user, template_id)
    return template.filename, template.content_type, template.data


async def delete_template(
    session: AsyncSession, user: User, template_id: uuid.UUID, ctx: RequestContext
) -> None:
    """Documents already sent keep their status and report (they name the template)."""
    template = await _template(session, user, template_id)
    record_event(
        session,
        "esign.template_deleted",
        ctx,
        actor_id=user.id,
        template_id=str(template.id),
        summary=f"Removed e-signature template {template.name}",
    )
    await session.delete(template)
    await session.commit()


# --- documents ----------------------------------------------------------------------------


def _out(doc: EsignDocument) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        name=doc.name,
        template_id=doc.template_id,
        template_name=doc.template_name,
        pandadoc_id=doc.pandadoc_id,
        status=doc.status,
        status_label="Sending" if doc.send_pending else label_of(doc.status),
        stage=stage_of(doc.status),
        send_pending=doc.send_pending,
        subject=doc.subject,
        recipients=[RecipientOut.model_validate(r) for r in doc.recipients],
        countersign=any(r.get("countersigner") for r in doc.recipients),
        your_turn=your_turn(doc),
        error=doc.error,
        created_at=doc.created_at,
        sent_at=doc.sent_at,
        viewed_at=doc.viewed_at,
        completed_at=doc.completed_at,
        status_changed_at=doc.status_changed_at,
    )


def your_turn(doc: EsignDocument) -> bool:
    """The sender countersigns, everyone else has signed, and the sender hasn't yet."""
    if doc.send_pending or stage_of(doc.status) not in (Stage.SENT, Stage.VIEWED):
        return False
    mine = [r for r in doc.recipients if r.get("countersigner")]
    others = [r for r in doc.recipients if not r.get("countersigner")]
    return (
        bool(mine)
        and not mine[0].get("has_completed")
        and all(r.get("has_completed") for r in others)
    )


async def _document(session: AsyncSession, user: User, document_id: uuid.UUID) -> EsignDocument:
    doc = await session.get(EsignDocument, document_id)
    if doc is None or doc.sender_id != user.id:
        raise DocumentNotFoundError()
    return doc


def _event(
    session: AsyncSession,
    doc: EsignDocument,
    event: str,
    *,
    status: str | None = None,
    recipient: str | None = None,
    detail: str | None = None,
    delivery_id: str | None = None,
    sequence: int = 0,
) -> None:
    session.add(
        EsignEvent(
            document_id=doc.id,
            event=event,
            status=status,
            recipient_email=recipient,
            detail=detail,
            delivery_id=delivery_id,
            sequence=sequence,
        )
    )


def _set_status(doc: EsignDocument, status: str, when: datetime | None = None) -> bool:
    """Move the document to `status`; False when that changes nothing. A finished document
    doesn't go back (webhooks can arrive out of order)."""
    if not status or status == doc.status:
        return False
    if doc.status in TERMINAL and status not in TERMINAL:
        return False
    now = when or utcnow()
    doc.status = status
    doc.status_changed_at = now
    stage = stage_of(status)
    if stage in (Stage.SENT, Stage.VIEWED, Stage.COMPLETED) and doc.sent_at is None:
        doc.sent_at = now
    if stage in (Stage.VIEWED, Stage.COMPLETED) and doc.viewed_at is None:
        doc.viewed_at = now
    if stage == Stage.COMPLETED and doc.completed_at is None:
        doc.completed_at = now
    if stage != Stage.FAILED:
        doc.error = None
    return True


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _merge_recipients(doc: EsignDocument, remote: object) -> None:
    """has_completed from PandaDoc's recipients (by email)."""
    if not isinstance(remote, list):
        return
    done = {
        str(r.get("email", "")).lower(): r
        for r in remote
        if isinstance(r, dict) and r.get("has_completed")
    }
    if not done:
        return
    merged = []
    for r in doc.recipients:
        hit = done.get(r["email"].lower())
        if hit and not r.get("has_completed"):
            r = {
                **r,
                "has_completed": True,
                "completed_at": r.get("completed_at") or utcnow().isoformat(),
            }
        merged.append(r)
    doc.recipients = merged


async def _send_now(session: AsyncSession, doc: EsignDocument, api: pandadoc.PandaDoc) -> None:
    """PandaDoc has the document as a draft: email it to the signers."""
    assert doc.pandadoc_id is not None  # noqa: S101 - only called for created documents
    if doc.signature_layout and not await _has_event(session, doc, "fields_added"):
        details = await api.details(doc.pandadoc_id)
        ids = {
            str(r.get("email", "")).lower(): str(r["id"])
            for r in details.get("recipients") or []
            if isinstance(r, dict) and r.get("id")
        }
        boxes = signer_boxes(doc.signature_layout, len(doc.recipients))
        pairs = [
            (ids[r["email"].lower()], box)
            for r, box in zip(doc.recipients, boxes, strict=True)
            if r["email"].lower() in ids
        ]
        await api.add_signature_boxes(doc.pandadoc_id, pairs)
        _event(
            session,
            doc,
            "fields_added",
            detail=f"Signature box for {len(pairs)} signer{'s' if len(pairs) != 1 else ''} "
            f"on page {doc.signature_layout['page']}",
        )
        await session.flush()
    status = await api.send(doc.pandadoc_id, doc.subject, doc.message)
    doc.send_pending = False
    _set_status(doc, status)
    _event(session, doc, "sent", status=status, detail="Emailed to the signers by PandaDoc")


_TRUE = frozenset({"true", "1", "yes", "on", "y"})


def _field_values(
    template: EsignTemplate, given: dict[str, str]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """The sender's values for the template's dynamic fields: what's kept on the document,
    and PandaDoc's `fields` ({id: {"value", "role"}}). PandaDoc refuses a file whose tag ids
    aren't all in `fields`, so every one is declared: those left empty for the signer."""
    fillable = {t["id"]: t for t in template.field_tags if t.get("prefillable")}
    unknown = sorted(set(given) - set(fillable))
    if unknown:
        raise SendRejectedError(f"This template has no field {', '.join(unknown)}.")
    kept: dict[str, Any] = {}
    fields: dict[str, dict[str, Any]] = {
        t["id"]: {"value": False if t["type"] == "checkbox" else "", "role": t["role"]}
        for t in template.field_tags
        if t.get("id")
    }
    for field_id, raw in given.items():
        text = raw.strip()
        if not text:
            continue
        tag = fillable[field_id]
        value: Any
        if tag["type"] == "date":
            try:
                day = date.fromisoformat(text[:10])
            except ValueError as exc:
                raise SendRejectedError(f"{field_id}: enter a date as YYYY-MM-DD.") from exc
            kept[field_id] = day.isoformat()
            value = f"{day.isoformat()}T00:00:00.000Z"
        elif tag["type"] == "checkbox":
            value = text.lower() in _TRUE
            kept[field_id] = value
        else:
            value = kept[field_id] = text[:1000]
        fields[field_id] = {"value": value, "role": tag["role"]}
    return kept, fields


async def _has_event(session: AsyncSession, doc: EsignDocument, event: str) -> bool:
    found = await session.scalar(
        select(EsignEvent.id)
        .where(EsignEvent.document_id == doc.id, EsignEvent.event == event)
        .limit(1)
    )
    return found is not None


async def send_document(
    session: AsyncSession, user: User, body: SendRequest, ctx: RequestContext
) -> DocumentOut:
    """Upload the template to PandaDoc as a new document, wait until it is ready, send it.
    When PandaDoc takes longer than usual, the document is sent as soon as its webhook says
    it's ready (or with "Retry send")."""
    api = pandadoc.client()
    template = await _template(session, user, body.template_id)
    people = [(str(r.email).lower(), r.first_name, r.last_name, False) for r in body.recipients]
    if body.countersign:
        if any(email == user.email.lower() for email, *_ in people):
            raise SendRejectedError(
                "You're already a signer: remove yourself, you countersign last."
            )
        first, _, last = user.full_name.strip().partition(" ")
        people.append((user.email.lower(), first or user.email, last, True))
    if len(people) > 10:
        raise SendRejectedError("At most 10 signers, you included.")
    recipients = [
        {
            "email": email,
            "name": f"{first_name} {last_name}".strip(),
            "role": f"signer{i}",
            "has_completed": False,
            "completed_at": None,
            **({"countersigner": True} if countersigner else {}),
        }
        for i, (email, first_name, last_name, countersigner) in enumerate(people, start=1)
    ]
    # Countersigning: everyone else signs first (together), the sender after them
    signers = [
        pandadoc.Signer(
            email,
            first_name,
            last_name,
            f"signer{i}",
            (2 if countersigner else 1) if body.countersign else None,
        )
        for i, (email, first_name, last_name, countersigner) in enumerate(people, start=1)
    ]
    needed = field_tags.signers_needed(template.field_tags)
    if len(signers) < needed:
        you = " (you countersign as the last one)" if body.countersign else ""
        raise SendRejectedError(
            f"This template has fields for {needed} signers (signer1 to signer{needed}){you}: "
            f"add {needed - len(signers)} more."
        )
    values, fields = _field_values(template, body.values)
    name = (body.name or "").strip() or template.name
    created = await api.create_from_file(
        name, template.filename, template.content_type, template.data, signers, fields
    )
    doc = EsignDocument(
        sender_id=user.id,
        template_id=template.id,
        template_name=template.name,
        pandadoc_id=str(created["id"]),
        name=name,
        status=str(created.get("status") or "document.uploaded"),
        send_pending=True,
        subject=(body.subject or "").strip() or None,
        message=(body.message or "").strip() or None,
        signature_layout=template.signature_layout,
        field_values=values,
        recipients=recipients,
        status_changed_at=utcnow(),
    )
    session.add(doc)
    await session.flush()
    _event(session, doc, "created", status=doc.status, detail="Uploaded to PandaDoc")
    record_event(
        session,
        "esign.sent",
        ctx,
        actor_id=user.id,
        document_id=str(doc.id),
        summary=(f"Sent {name} for signature to " + ", ".join(str(r["email"]) for r in recipients)),
    )
    await session.commit()  # the PandaDoc document exists: keep track of it whatever follows

    await _wait_and_send(session, doc, api, ctx, user)
    return _out(doc)


async def _wait_and_send(
    session: AsyncSession,
    doc: EsignDocument,
    api: pandadoc.PandaDoc,
    ctx: RequestContext,
    user: User,
) -> None:
    assert doc.pandadoc_id is not None  # noqa: S101
    try:
        for attempt in range(POLL_ATTEMPTS):
            status = str((await api.status(doc.pandadoc_id)).get("status", ""))
            if status == "document.draft":
                await _send_now(session, doc, api)
                break
            if status == "document.error":
                doc.send_pending = False
                _set_status(doc, "failed")
                doc.error = "PandaDoc couldn't process the file."
                _event(session, doc, "failed", status="failed", detail=doc.error)
                break
            if status and status != "document.uploaded":  # sent already (e.g. by a webhook)
                doc.send_pending = False
                _set_status(doc, status)
                break
            if attempt < POLL_ATTEMPTS - 1:
                await asyncio.sleep(POLL_SECONDS)
    except PandaDocError as exc:
        doc.error = exc.message
        _event(session, doc, "send_failed", detail=exc.message)
        record_event(
            session,
            "esign.send_failed",
            ctx,
            actor_id=user.id,
            document_id=str(doc.id),
            summary=f"PandaDoc didn't send {doc.name}: {exc.message}",
        )
    await session.commit()


async def retry_send(
    session: AsyncSession, user: User, document_id: uuid.UUID, ctx: RequestContext
) -> DocumentOut:
    doc = await _document(session, user, document_id)
    if not doc.send_pending or doc.pandadoc_id is None:
        raise DocumentNotSendableError("This document was already sent.")
    await _wait_and_send(session, doc, pandadoc.client(), ctx, user)
    return _out(doc)


async def list_documents(
    session: AsyncSession,
    user: User,
    stage: Stage | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> DocumentPage:
    query = select(EsignDocument).where(EsignDocument.sender_id == user.id)
    if stage is not None:
        statuses = [s for s in STATUS_LABELS if stage_of(s) == stage]
        query = query.where(EsignDocument.status.in_(statuses))
    if search:
        like = f"%{search.strip().lower()}%"
        query = query.where(
            func.lower(EsignDocument.name).like(like)
            | func.lower(cast(EsignDocument.recipients, Text)).like(like)
        )
    total = int(await session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    docs = await session.scalars(
        query.order_by(EsignDocument.created_at.desc()).limit(limit).offset(offset)
    )
    return DocumentPage(items=[_out(d) for d in docs], total=total)


async def document_detail(
    session: AsyncSession, user: User, document_id: uuid.UUID
) -> DocumentDetail:
    doc = await _document(session, user, document_id)
    events = await session.scalars(
        select(EsignEvent)
        .where(EsignEvent.document_id == doc.id)
        .order_by(EsignEvent.created_at, EsignEvent.sequence)
    )
    return DocumentDetail(
        **_out(doc).model_dump(),
        message=doc.message,
        field_values=doc.field_values,
        events=[EventOut.model_validate(e) for e in events],
    )


async def refresh_document(
    session: AsyncSession, user: User, document_id: uuid.UUID
) -> DocumentDetail:
    """Ask PandaDoc for the latest status (when webhooks can't reach this server)."""
    doc = await _document(session, user, document_id)
    if doc.pandadoc_id is None:
        raise DocumentNotSendableError("This document never reached PandaDoc.")
    details = await pandadoc.client().details(doc.pandadoc_id)
    status = str(details.get("status") or "")
    when = _parse_time(details.get("date_modified"))
    if _set_status(doc, status, when):
        _event(session, doc, "refreshed", status=status, detail="Status read from PandaDoc")
    _merge_recipients(doc, details.get("recipients"))
    await session.commit()
    return await document_detail(session, user, document_id)


async def download(session: AsyncSession, user: User, document_id: uuid.UUID) -> tuple[str, bytes]:
    doc = await _document(session, user, document_id)
    if doc.pandadoc_id is None:
        raise DocumentNotSendableError("This document never reached PandaDoc.")
    data = await pandadoc.client().download(
        doc.pandadoc_id, completed=stage_of(doc.status) == Stage.COMPLETED
    )
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in doc.name).strip() or "doc"
    suffix = " (signed)" if stage_of(doc.status) == Stage.COMPLETED else ""
    return f"{safe}{suffix}.pdf", data


SESSION_SECONDS = 900


async def countersign_session(
    session: AsyncSession, user: User, document_id: uuid.UUID, ctx: RequestContext
) -> SigningSession:
    """Open the sender's own signing session, once everyone else has signed. Statuses are
    read from PandaDoc first, so it works without webhooks too."""
    doc = await _document(session, user, document_id)
    if doc.pandadoc_id is None or not any(r.get("countersigner") for r in doc.recipients):
        raise DocumentNotSendableError("You aren't a signer of this document.")
    if not your_turn(doc):
        await refresh_document(session, user, document_id)
        doc = await _document(session, user, document_id)
    if not your_turn(doc):
        raise DocumentNotSendableError(
            "Not your turn yet: the other signers haven't all signed."
            if stage_of(doc.status) in (Stage.SENT, Stage.VIEWED)
            else "This document can't be signed any more."
        )
    me = next(r for r in doc.recipients if r.get("countersigner"))
    assert doc.pandadoc_id is not None  # noqa: S101 - checked above
    session_id = await pandadoc.client().signing_session(
        doc.pandadoc_id, me["email"], SESSION_SECONDS
    )
    _event(session, doc, "countersign_opened", recipient=me["email"], detail="Signing in the app")
    record_event(
        session,
        "esign.countersign_opened",
        ctx,
        actor_id=user.id,
        document_id=str(doc.id),
        summary=f"Opened {doc.name} to countersign",
    )
    await session.commit()
    return SigningSession(
        session_id=session_id,
        url=f"https://app.pandadoc.com/s/{session_id}/",
        expires_in_seconds=SESSION_SECONDS,
    )


# --- report -------------------------------------------------------------------------------


async def report(session: AsyncSession, user: User) -> EsignReport:
    docs = list(
        await session.scalars(select(EsignDocument).where(EsignDocument.sender_id == user.id))
    )
    counts = dict.fromkeys(Stage, 0)
    for d in docs:
        counts[stage_of(d.status)] += 1
    reached = sum(counts[s] for s in (Stage.SENT, Stage.VIEWED, Stage.COMPLETED, Stage.DECLINED))
    reached += counts[Stage.VOIDED]
    hours = [
        (d.completed_at - d.sent_at).total_seconds() / 3600
        for d in docs
        if d.completed_at and d.sent_at and d.completed_at >= d.sent_at
    ]
    since = utcnow() - timedelta(days=30)
    usage: dict[str, list[int]] = {}
    for d in docs:
        row = usage.setdefault(d.template_name, [0, 0])
        row[0] += 1
        row[1] += stage_of(d.status) == Stage.COMPLETED
    return EsignReport(
        total=len(docs),
        by_stage=[StageCount(stage=s, count=n) for s, n in counts.items()],
        completion_rate=(counts[Stage.COMPLETED] / reached) if reached else None,
        avg_hours_to_complete=(sum(hours) / len(hours)) if hours else None,
        awaiting_signature=counts[Stage.SENT] + counts[Stage.VIEWED],
        awaiting_you=sum(1 for d in docs if your_turn(d)),
        sent_last_30_days=sum(1 for d in docs if d.sent_at and d.sent_at >= since),
        completed_last_30_days=sum(1 for d in docs if d.completed_at and d.completed_at >= since),
        templates=sorted(
            (TemplateUsage(template_name=k, sent=v[0], completed=v[1]) for k, v in usage.items()),
            key=lambda t: -t.sent,
        ),
    )


# --- webhook ------------------------------------------------------------------------------


def verify_signature(body: bytes, signature: str | None) -> None:
    key = get_settings().pandadoc_webhook_key
    if key is None:
        raise WebhookNotConfiguredError()
    if not signature:
        raise WebhookRejectedError()
    expected = hmac.new(key.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise WebhookRejectedError()


async def handle_webhook(
    session: AsyncSession, body: bytes, signature: str | None, delivery_id: str | None
) -> int:
    """Apply PandaDoc's events to the documents they're about. Returns how many applied.
    Events for documents this app didn't send (others in the PandaDoc account) are ignored."""
    verify_signature(body, signature)
    if delivery_id and await session.scalar(
        select(EsignEvent.id).where(EsignEvent.delivery_id == delivery_id).limit(1)
    ):
        return 0  # a retried delivery: already applied
    try:
        events = json.loads(body)
    except ValueError:
        return 0
    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, list):
        return 0
    applied = 0
    for sequence, item in enumerate(events):
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            continue
        data: dict[str, Any] = item["data"]
        doc = await session.scalar(
            select(EsignDocument).where(EsignDocument.pandadoc_id == str(data.get("id", "")))
        )
        if doc is None:
            continue
        await _apply(session, doc, str(item.get("event", "")), data, delivery_id, sequence)
        applied += 1
    await session.commit()
    return applied


async def _apply(
    session: AsyncSession,
    doc: EsignDocument,
    event: str,
    data: dict[str, Any],
    delivery_id: str | None,
    sequence: int,
) -> None:
    status = str(data.get("status") or "")
    when = _parse_time(data.get("date_modified"))
    if event == "document_creation_failed":
        error = _dict(data.get("error"))
        doc.send_pending = False
        _set_status(doc, "failed")
        doc.error = str(error.get("detail") or "PandaDoc couldn't create the document.")[:1000]
        _event(session, doc, event, status="failed", detail=doc.error, delivery_id=delivery_id)
        return
    if event == "recipient_completed":
        action_by = _dict(data.get("action_by"))
        email = str(action_by.get("email", "")).lower() or None
        at = str(data.get("action_date") or utcnow().isoformat())
        doc.recipients = [
            {**r, "has_completed": True, "completed_at": r.get("completed_at") or at}
            if email and r["email"].lower() == email
            else r
            for r in doc.recipients
        ]
        _event(
            session,
            doc,
            event,
            status=status or None,
            recipient=email,
            detail="Signed",
            delivery_id=delivery_id,
            sequence=sequence,
        )
        _set_status(doc, status, when)
        return
    _merge_recipients(doc, data.get("recipients"))
    changed = _set_status(doc, status, when)
    _event(
        session,
        doc,
        event or "webhook",
        status=status or None,
        detail=label_of(status) if status else None,
        delivery_id=delivery_id,
        sequence=sequence,
    )
    # Took longer than the send request waited: send it now that it's ready
    if changed and status == "document.draft" and doc.send_pending:
        try:
            await _send_now(session, doc, pandadoc.client())
        except Exception as exc:  # the webhook still records the status; retry by hand
            doc.error = getattr(exc, "message", str(exc))
            log.warning("sending e-signature document %s failed", doc.id, exc_info=True)
