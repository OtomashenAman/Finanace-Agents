"""The delivery agent (3.5): posts the approved invoice to the ERP, emails it to the client
with its PDF and a link to view it online, and sends monthly statements on its own.

A sent invoice also goes into the client's billing history, which the monitor (AR 1.3.2)
reviews credit terms from.
"""

import hashlib
import re
import secrets
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.finance_pod import mail, pdf
from src.app.finance_pod.billing.models import (
    FpLabSubmission,
    FpSalesInvoice,
    FpStatement,
    SalesInvoiceStatus,
    SubmissionStatus,
)
from src.app.finance_pod.clients.models import FpClient, FpClientHistory
from src.app.finance_pod.erp import ErpSalesInvoice, get_erp
from src.app.jobs.queue import JobContext, daily, handler
from src.app.service_pod.core.messaging import providers

STATEMENT_JOB = "fpod.monthly_statements"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invoice_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/client-invoice/{token}"


def due_date(terms: str, issued: date) -> date:
    match = re.search(r"net\s*(\d+)", terms, re.IGNORECASE)
    return issued + timedelta(days=int(match.group(1))) if match else issued


def _money(v: Decimal, cur: str) -> str:
    return f"{cur} {v:,.2f}"


def invoice_pdf(inv: FpSalesInvoice, submission: FpLabSubmission) -> bytes:
    org = get_settings().email_sender_name
    lines: list[pdf.Line] = [
        (org, 16, True),
        (f"Invoice {inv.reference}", 13, True),
        ("", 6, False),
        (f"Bill to: {inv.client_name} (account {inv.client_code})", 10, False),
        (
            "Invoice date: "
            + (mail.long_date(inv.issue_date) if inv.issue_date else "on sending")
            + "    Due: "
            + (mail.long_date(inv.due_date) if inv.due_date else "per terms")
            + f"    Terms: {inv.payment_terms}",
            10,
            False,
        ),
        (
            f"Lab submission: {submission.reference}    Turnaround: {submission.turnaround}",
            10,
            False,
        ),
        ("", 6, False),
        ("Item  |  Service  |  Qty x unit price  =  amount", 9, True),
    ]
    for ln in inv.lines:
        stone = ln.stone_type + (f", {ln.carat} ct" if ln.carat is not None else "")
        lines.append(
            (
                f"{ln.item_ref}  |  {ln.description} ({stone})  |  "
                f"{ln.quantity} x {ln.unit_price:,.2f}  =  {ln.amount:,.2f} {inv.currency}",
                9,
                False,
            )
        )
    lines += [
        ("", 6, False),
        (f"Subtotal: {_money(inv.subtotal, inv.currency)}", 10, False),
    ]
    if inv.discount_total:
        lines.append(
            (f"Includes contract discounts of {_money(inv.discount_total, inv.currency)}", 9, False)
        )
    lines += [
        (
            f"{inv.tax_name or 'Tax'} ({mail.percent(inv.tax_rate)}): "
            f"{_money(inv.tax, inv.currency)}",
            10,
            False,
        ),
        (f"Total due: {_money(inv.total, inv.currency)}", 12, True),
        ("", 6, False),
        (f"Please quote {inv.reference} with your payment.", 9, False),
    ]
    return pdf.render(lines)


async def deliver(
    session: AsyncSession,
    inv: FpSalesInvoice,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID | None,
) -> None:
    """Post, email and record the approved invoice (3.5.1). The caller commits."""
    submission = await session.get(FpLabSubmission, inv.submission_id)
    assert submission is not None  # noqa: S101 - the foreign key holds it
    today = utcnow().date()
    inv.issue_date, inv.due_date = today, due_date(inv.payment_terms, today)
    erp = get_erp()
    inv.erp_ref = await erp.post_sales_invoice(
        ErpSalesInvoice(
            number=inv.reference,
            customer_code=inv.client_code,
            currency=inv.currency,
            total=inv.total,
            tax=inv.tax,
            issue_date=inv.issue_date,
            due_date=inv.due_date,
        )
    )
    token = secrets.token_urlsafe(32)
    inv.token_hash = token_hash(token)
    inv.token_expires_at = utcnow() + timedelta(days=get_settings().invoice_link_days)
    org = get_settings().email_sender_name
    document = invoice_pdf(inv, submission)
    deposit = (
        f"\nA {mail.percent(inv.deposit_pct)} deposit applies to your account.\n"
        if inv.deposit_pct
        else ""
    )
    assert inv.due_date is not None  # noqa: S101 - set above
    sent = await mail.send(
        session,
        kind=mail.MailKind.CLIENT_INVOICE,
        to_email=inv.bill_to_email,
        to_name=inv.client_name,
        subject=f"{org}: invoice {inv.reference} for {submission.reference}",
        body=(
            f"Hello {inv.client_name},\n\nYour reports for {submission.reference} are issued. "
            f"Invoice {inv.reference} for {_money(inv.total, inv.currency)} is attached, due "
            f"{mail.long_date(inv.due_date)} ({inv.payment_terms}).\n{deposit}\nView it online: "
            f"{invoice_url(token)}\n\nThank you,\n{org}"
        ),
        sent_by=actor_id,
        attachments=[providers.Attachment(f"{inv.reference}.pdf", "application/pdf", document)],
    )
    inv.status, inv.sent_at = SalesInvoiceStatus.SENT, utcnow()
    inv.version += 1
    submission.status = SubmissionStatus.INVOICED
    existing = await session.scalar(
        select(FpClientHistory).where(
            FpClientHistory.client_code == inv.client_code,
            FpClientHistory.invoice_number == inv.reference,
        )
    )
    if existing is None:
        session.add(
            FpClientHistory(
                client_code=inv.client_code,
                invoice_number=inv.reference,
                amount=inv.total,
                issued_on=inv.issue_date,
                due_on=inv.due_date,
                paid_on=None,
            )
        )
    days = (
        (inv.sent_at - submission.report_issued_at).total_seconds() / 86400
        if submission.report_issued_at
        else None
    )
    record_event(
        session,
        "fpod.sales_invoice_sent",
        ctx,
        actor_id=actor_id,
        invoice=inv.reference,
        client_code=inv.client_code,
        erp=erp.name,
        summary=f"Delivery agent posted {inv.reference} ({_money(inv.total, inv.currency)}) to "
        f"the ERP ({inv.erp_ref}) and emailed it to {inv.client_name} at {inv.bill_to_email}"
        + (f", {days:.1f} day(s) after the report was issued" if days is not None else "")
        + mail.outcome(sent),
    )


def _period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _previous_month(today: date) -> tuple[str, date]:
    """The month a statement on `today` covers, and its last day."""
    last = today.replace(day=1) - timedelta(days=1)
    return _period(last), last


async def send_statements(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    actor_id: uuid.UUID | None,
    today: date | None = None,
) -> dict[str, Any]:
    """A statement to every client with something open, for last month (once per client and
    month). The caller commits."""
    today = today or utcnow().date()
    period, as_of = _previous_month(today)
    sent = skipped = 0
    org = get_settings().email_sender_name
    for client in list(await session.scalars(select(FpClient).order_by(FpClient.code))):
        if await session.scalar(
            select(FpStatement.id).where(
                FpStatement.client_code == client.code, FpStatement.period == period
            )
        ):
            skipped += 1
            continue
        rows = list(
            await session.scalars(
                select(FpClientHistory)
                .where(
                    FpClientHistory.client_code == client.code, FpClientHistory.paid_on.is_(None)
                )
                .where(FpClientHistory.issued_on <= as_of)
                .order_by(FpClientHistory.issued_on)
            )
        )
        if not rows:
            continue
        balance = sum((r.amount for r in rows), Decimal("0"))
        month = f"{as_of:%B %Y}"
        lines: list[pdf.Line] = [
            (org, 16, True),
            (f"Statement of account: {month}", 13, True),
            (f"{client.name} (account {client.code})", 10, False),
            ("", 6, False),
            ("Invoice  |  Issued  |  Due  |  Amount  |  Status", 9, True),
        ]
        for r in rows:
            late = (today - r.due_on).days
            status = f"{mail.plural(late, 'day')} overdue" if late > 0 else "open"
            lines.append(
                (
                    f"{r.invoice_number}  |  {mail.long_date(r.issued_on)}  |  "
                    f"{mail.long_date(r.due_on)}  |  {r.amount:,.2f}  |  {status}",
                    9,
                    False,
                )
            )
        lines += [("", 6, False), (f"Balance due: {_money(balance, client.currency)}", 12, True)]
        email = await mail.send(
            session,
            kind=mail.MailKind.CLIENT_STATEMENT,
            to_email=client.billing_email,
            to_name=client.name,
            subject=f"{org}: statement for {month}, account {client.code}",
            body=(
                f"Hello {client.name},\n\nYour statement for {month} is attached: "
                f"{mail.plural(len(rows), 'open invoice')}, balance "
                f"{_money(balance, client.currency)}.\n\nThank you,\n{org}"
            ),
            sent_by=actor_id,
            attachments=[
                providers.Attachment(
                    f"statement-{client.code}-{period}.pdf", "application/pdf", pdf.render(lines)
                )
            ],
        )
        await session.flush()
        session.add(
            FpStatement(
                client_code=client.code,
                period=period,
                open_balance=balance,
                open_invoices=len(rows),
                email_id=email.id,
            )
        )
        sent += 1
    record_event(
        session,
        "fpod.statements_sent",
        ctx,
        actor_id=actor_id,
        period=period,
        sent=sent,
        summary=f"Delivery agent sent {sent} monthly statement(s) for {period}"
        + (f" ({skipped} already sent)" if skipped else ""),
    )
    return {"period": period, "sent": sent, "already_sent": skipped}


_SYSTEM = RequestContext(ip=None, user_agent="background worker")


@daily(STATEMENT_JOB)
@handler(STATEMENT_JOB)
async def monthly_statements(
    session: AsyncSession, payload: dict[str, Any], ctx: JobContext
) -> None:
    """Daily; on the first of the month, last month's statements go out (3.5.1.b)."""
    today = date.fromisoformat(payload["date"]) if payload.get("date") else utcnow().date()
    if today.day != 1:
        return
    await send_statements(session, _SYSTEM, actor_id=None, today=today)
