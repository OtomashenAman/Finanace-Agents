"""Mail the Finance POD sends to vendors: quote requests, onboarding portal links, POs.

Sent through the app's email transport (EMAIL_PROVIDER: the outbox in development, Brevo or
Microsoft 365), and logged whatever the outcome: sent, refused (nothing went out) or unknown
(a timeout: it may have gone out; check the provider before sending again). With
EMAIL_TEST_RECIPIENT set, every mail goes to the tester, its subject naming the real one.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.clock import utcnow
from src.app.common.models import (
    Base,
    CreatedAtMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)
from src.app.core.config import get_settings
from src.app.service_pod.core.messaging import providers


class MailKind(StrEnum):
    QUOTE_REQUEST = "quote_request"
    PORTAL_INVITE = "portal_invite"
    PURCHASE_ORDER = "purchase_order"
    RECEIPT_REQUEST = "receipt_request"  # Phase 3.6: ask the receiver to confirm delivery
    VENDOR_QUERY = "vendor_query"  # Phase 3.5: an invoice variance (credit note, rejection)
    REMITTANCE = "remittance"  # Phase 5: what was paid, after a run is released
    QUERY_ANSWER = "query_answer"  # Phase 5: the answer to a vendor's question
    CLIENT_INVITE = "client_invite"  # AR 1.1: the client's secure application link
    CLIENT_GAPS = "client_gaps"  # AR 1.1.2.c: what's missing or wrong, with a new link
    CLIENT_WELCOME = "client_welcome"  # AR 1.3: the account details, once approved


class MailStatus(StrEnum):
    SENT = "sent"
    FAILED = "failed"  # refused by the provider: nothing went out
    UNKNOWN = "unknown"  # no clear answer: check the provider before sending again


class FpEmail(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "fpod_emails"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (enum_check("kind", MailKind), enum_check("status", MailStatus))

    kind: Mapped[MailKind] = mapped_column(string_enum(MailKind, 24))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fpod_requests.id", ondelete="CASCADE"), index=True
    )
    to_email: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[MailStatus] = mapped_column(string_enum(MailStatus, 16))
    provider: Mapped[str] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(300))
    simulated: Mapped[bool]
    error: Mapped[str | None] = mapped_column(String(500))
    sent_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    sent_at: Mapped[datetime | None]


async def send(
    session: AsyncSession,
    *,
    kind: MailKind,
    to_email: str,
    to_name: str | None,
    subject: str,
    body: str,
    sent_by: uuid.UUID,
    request_id: uuid.UUID | None = None,
    attachments: list[providers.Attachment] | None = None,
) -> FpEmail:
    """Send now and log it (the caller commits). Never raises for a provider failure: the
    returned row says what happened."""
    settings = get_settings()
    provider = providers.get_email_provider()
    redirect = settings.email_test_recipient
    row = FpEmail(
        kind=kind,
        request_id=request_id,
        to_email=to_email,
        subject=subject[:300],
        body=body,
        provider=provider.name,
        simulated=provider.simulated,
        sent_by=sent_by,
        status=MailStatus.UNKNOWN,
    )
    email = providers.OutgoingEmail(
        to_email=redirect or to_email,
        to_name=None if redirect else to_name,
        subject=f"[TEST for {to_email}] {subject}" if redirect else subject,
        body=body,
        sender=provider.sender or "",
        sender_name=settings.email_sender_name,
        attachments=attachments or [],
    )
    try:
        row.provider_message_id = await provider.send(email)
    except providers.SendRefusedError as exc:
        row.status, row.error = MailStatus.FAILED, str(exc)[:500]
    except Exception as exc:  # timeout / network: it may have gone out
        row.status, row.error = MailStatus.UNKNOWN, (str(exc) or type(exc).__name__)[:500]
    else:
        row.status, row.sent_at = MailStatus.SENT, utcnow()
    session.add(row)
    return row


def outcome(row: FpEmail) -> str:
    """For audit sentences: how the send went."""
    if row.status == MailStatus.SENT:
        return " (simulated: outbox, nothing left the app)" if row.simulated else ""
    if row.status == MailStatus.FAILED:
        return f" but the provider refused it: {row.error}"
    return f" but the outcome is unknown ({row.error}); check the provider before resending"
