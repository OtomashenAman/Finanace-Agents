"""Customer replies straight from the Microsoft 365 mailbox (EMAIL_PROVIDER=microsoft with
AGENT_POLL_INTERVAL set). Every interval the worker reads the inbox from where it stopped
and imports a mail only when its headers answer a message sent from a case and it comes
from the address that message went to: the same rules as importing a reply by hand.
Anything else in the inbox is left alone."""

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.jobs.queue import JobContext, every, handler
from src.app.service_pod.core.messaging import service
from src.app.service_pod.core.messaging.graph import GraphMailbox
from src.app.service_pod.core.messaging.inbound import normalize_id, parse_eml
from src.app.service_pod.core.messaging.models import (
    Direction,
    MessageStatus,
    PodMailboxCursor,
    PodMessage,
)
from src.app.service_pod.core.messaging.schemas import ReplyImport

MAILBOX_JOB = "pod.read_mailbox"
FIRST_LOOK_BACK = timedelta(days=7)  # the first read starts this far back

log = logging.getLogger(__name__)
_MAILBOX = RequestContext(ip=None, user_agent="mailbox reader")


def _interval() -> int | None:
    s = get_settings()
    return s.mailbox_poll_seconds if s.email_provider == "microsoft" else None


@every(MAILBOX_JOB, _interval)
@handler(MAILBOX_JOB)
async def read_mailbox(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    if _interval() is None:
        return
    mailbox = GraphMailbox.from_settings()
    cursor = await session.get(PodMailboxCursor, mailbox.mailbox)
    if cursor is None:
        cursor = PodMailboxCursor(
            mailbox=mailbox.mailbox, received_after=utcnow() - FIRST_LOOK_BACK
        )
        session.add(cursor)
        await session.commit()
    # Who replies can only be someone mail went to (or the tester, in test mode)
    sent = list(
        await session.scalars(
            select(PodMessage).where(
                PodMessage.direction == Direction.OUTBOUND,
                PodMessage.status == MessageStatus.SENT,
                PodMessage.provider == "microsoft",
            )
        )
    )
    recipients = {m.to_email.lower() for m in sent}
    if tester := get_settings().email_test_recipient:
        recipients.add(tester.lower())
    by_id = {normalize_id(m.provider_message_id): m for m in sent if m.provider_message_id}

    for item in await mailbox.inbox_since(cursor.received_after):
        if item.sender in recipients:
            raw = await mailbox.mime(item.id)
            try:
                parsed = parse_eml(raw)
                original = next((by_id[i] for i in parsed.replies_to if i in by_id), None)
                if original is not None:
                    await service.import_reply(
                        session, None, original.case_id, ReplyImport(raw_eml=raw), _MAILBOX, ctx.llm
                    )
            except AppError as exc:  # e.g. no readable text, or not from the addressee
                await session.rollback()
                log.info("mailbox: left %s from %s alone: %s", item.id, item.sender, exc)
        cursor = await session.get(PodMailboxCursor, mailbox.mailbox)
        assert cursor is not None  # noqa: S101 - created above
        cursor.received_after = item.received_at
        await session.commit()
