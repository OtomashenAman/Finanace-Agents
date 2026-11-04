"""Sending an approved message. One attempt only: a second run of the same job (a worker
died mid-send) can't know whether the first went out, so it marks the outcome unknown."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.jobs.queue import JobContext, handler
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.messaging import providers
from src.app.service_pod.core.messaging.models import MessageStatus, PodArtifact, PodMessage
from src.app.service_pod.core.messaging.service import SEND_JOB

_SYSTEM = RequestContext(ip=None, user_agent="background worker")


@handler(SEND_JOB)
async def send_message(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    message = await session.get(PodMessage, uuid.UUID(payload["message_id"]), with_for_update=True)
    if message is None or message.status != MessageStatus.SENDING:
        return  # already settled
    case = await session.get(PodCase, message.case_id)
    assert case is not None  # noqa: S101 - cascade keeps them together

    def event(name: str, summary: str) -> None:
        record_event(
            session,
            name,
            _SYSTEM,
            actor_id=message.approved_by,
            run=case.reference,
            case_id=str(case.id),
            message_id=str(message.id),
            summary=f"{case.reference}: {summary}",
        )

    if ctx.attempt > 1:
        message.status = MessageStatus.SEND_UNKNOWN
        message.error = "The sending worker stopped mid-send; check the provider log."
        event("pod.message_send_unknown", "send outcome unknown, reconcile with the provider")
        return

    provider = providers.get_email_provider()
    if (provider.name, provider.sender) != (message.provider, message.sender):
        message.status = MessageStatus.SEND_FAILED
        message.error = "The email transport changed since approval; approve it again."
        event("pod.message_send_failed", message.error)
        return
    ids = [uuid.UUID(a) for a in message.artifact_ids]
    files = (
        # content is a deferred column: load it here, an async session can't load it lazily
        list(
            await session.scalars(
                select(PodArtifact)
                .options(undefer(PodArtifact.content))
                .where(PodArtifact.id.in_(ids))
            )
        )
        if ids
        else []
    )
    # Test mode: the mail goes to the tester, the subject names the real recipient
    redirect = get_settings().email_test_recipient
    email = providers.OutgoingEmail(
        to_email=redirect or message.to_email,
        to_name=None if redirect else message.to_name,
        subject=f"[TEST for {message.to_email}] {message.subject}" if redirect else message.subject,
        body=message.body,
        sender=message.sender or "",
        sender_name=get_settings().email_sender_name,
        attachments=[providers.Attachment(f.filename, f.content_type, f.content) for f in files],
    )
    try:
        provider_id = await provider.send(email)
    except providers.SendRefusedError as exc:
        message.status = MessageStatus.SEND_FAILED
        message.error = str(exc)[:500]
        event("pod.message_send_failed", f"provider refused the message: {message.error}")
        return
    except Exception as exc:
        message.status = MessageStatus.SEND_UNKNOWN
        message.error = str(exc)[:500] or type(exc).__name__
        event("pod.message_send_unknown", "send outcome unknown, reconcile with the provider")
        return
    message.status = MessageStatus.SENT
    message.provider_message_id = provider_id
    message.simulated = provider.simulated
    message.sent_at = utcnow()
    message.error = None
    message.version += 1
    note = " (simulated: outbox, nothing left the app)" if provider.simulated else ""
    if redirect:
        note += f" (test mode: delivered to {redirect})"
    event("pod.message_sent", f"sent '{message.subject}' to {message.to_email}{note}")
