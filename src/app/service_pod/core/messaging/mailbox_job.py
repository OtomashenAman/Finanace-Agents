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
from src.app.service_pod.core.messaging.graph import GraphMailbox, InboxItem
from src.app.service_pod.core.messaging.inbound import answers_subject, normalize_id, parse_eml
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
    seen = set(cursor.seen_ids or [])
    since = cursor.received_after

    for item in await mailbox.inbox_since(since):
        # Already looked at (same second as the cursor: Graph's "after" is finer than its times)
        if item.received_at <= since and item.id in seen:
            continue
        await _read_one(session, mailbox, item, recipients, sent, by_id, ctx)
        cursor = await session.get(PodMailboxCursor, mailbox.mailbox)
        assert cursor is not None  # noqa: S101 - created above
        if item.received_at > cursor.received_after:
            cursor.received_after, cursor.seen_ids = item.received_at, [item.id]
        else:
            cursor.seen_ids = [*(cursor.seen_ids or []), item.id]
        await session.commit()


def _original_by_subject(
    subject: str, sender: str, sent: list[PodMessage]
) -> tuple[PodMessage | None, int]:
    """The one sent message `subject` replies to ("Re: " + its subject), among those sent to
    `sender`, and how many matched (more than one: ambiguous, never guessed)."""
    matches = [
        m for m in sent if m.to_email.lower() == sender and answers_subject(subject, m.subject)
    ]
    return (matches[0] if len(matches) == 1 else None), len(matches)


async def _read_one(
    session: AsyncSession,
    mailbox: GraphMailbox,
    item: InboxItem,
    recipients: set[str],
    sent: list[PodMessage],
    by_id: dict[str, PodMessage],
    ctx: JobContext,
) -> None:
    """Import one inbox mail as a case reply when it answers a sent message; log why not."""
    if item.sender not in recipients:
        log.info(
            "mailbox: skipped %s from %s: not an address any case mailed", item.id, item.sender
        )
        return
    raw = await mailbox.mime(item.id)
    try:
        parsed = parse_eml(raw)
        original = next((by_id[i] for i in parsed.replies_to if i in by_id), None)
        by_subject = False
        if original is None and not parsed.replies_to:
            # Some mail apps (e.g. yopmail) send no In-Reply-To / References: fall back to
            # the subject, from the address that message went to
            original, count = _original_by_subject(parsed.subject, item.sender, sent)
            by_subject = original is not None
            if count > 1:
                log.info(
                    "mailbox: skipped %s from %s: subject %r answers %d sent messages; "
                    "import it by hand",
                    item.id, item.sender, parsed.subject, count,
                )  # fmt: skip
                return
        if original is None:
            log.info(
                "mailbox: skipped %s from %s: answers no message sent from a case "
                "(subject %r, %s)",
                item.id, item.sender, parsed.subject,
                "references unknown messages" if parsed.replies_to else "no reply headers",
            )  # fmt: skip
            return
        _, created = await service.import_reply(
            session,
            None,
            original.case_id,
            ReplyImport(raw_eml=raw),
            _MAILBOX,
            ctx.llm,
            match_by_subject=by_subject,
        )
        log.info(
            "mailbox: %s %s from %s as a reply on case %s (%s match)",
            "imported" if created else "already had",
            item.id, item.sender, original.case_id, "subject" if by_subject else "header",
        )  # fmt: skip
    except AppError as exc:  # e.g. no readable text, or not from the addressee
        await session.rollback()
        log.info("mailbox: left %s from %s alone: %s", item.id, item.sender, exc)
