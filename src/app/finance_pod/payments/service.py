"""Payments and vendor support.

Payment agent: proposes a run from approved invoices that are due within the horizon, or
can still take an early-pay discount; groups them by currency and bank; runs the risk checks
(bank-change history, unusual amount or vendor, possible duplicate payment, cash position).
People: the AP analyst calls back on flagged bank changes; treasury reviews and releases
with two different people. Vendor agent: once released, marks invoices paid and emails
remittances; answers vendors' status questions from the records; disputes go to an analyst.

Guardrails: no agent code path releases a payment (release needs two people); a payment to
recently changed bank details can't be released before the analyst's call-back; vendor
answers go only to the email address on file.
"""

import csv
import io
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.errors import AppError
from src.app.core.llm.base import LLMError, LLMProvider
from src.app.data_sources import crypto
from src.app.finance_pod import mail
from src.app.finance_pod.access import FinanceAccess, check_different_person
from src.app.finance_pod.invoices import agents as invoice_agents
from src.app.finance_pod.invoices.models import (
    ExceptionStatus,
    FpInvoice,
    FpInvoiceException,
    InvoiceStatus,
)
from src.app.finance_pod.onboarding.models import FpVendorBankAccount
from src.app.finance_pod.orders.models import FpPurchaseOrder
from src.app.finance_pod.payments.models import (
    CallbackStatus,
    FpPaymentApproval,
    FpPaymentItem,
    FpPaymentRun,
    FpVendorQuery,
    QueryIntent,
    QueryStatus,
    RunStatus,
)
from src.app.finance_pod.reference.models import FpVendor
from src.app.finance_pod.settings.service import current as current_settings
from src.app.service_pod.common import ai

CENT = Decimal("0.01")
LIVE_RUNS = (RunStatus.PROPOSED, RunStatus.PARTLY_APPROVED)
DUPLICATE_PAYMENT_DAYS = 60


class PaymentNotFoundError(AppError):
    status_code = 404
    code = "payment_not_found"
    message = "Not found."


class PaymentStateError(AppError):
    status_code = 409
    code = "payment_state"


class PaymentInvalidError(AppError):
    status_code = 422
    code = "payment_invalid"


# --- the payment agent: what's due, the discount, the risk checks --------------------------


def discount_terms(terms: str | None) -> tuple[Decimal, int] | None:
    """ "2/10 Net 30" -> (2%, within 10 days)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*/\s*(\d+)", terms or "")
    return (Decimal(m.group(1)), int(m.group(2))) if m else None


def net_days(terms: str | None) -> int:
    m = re.search(r"net\s*(\d+)", terms or "", re.IGNORECASE)
    return int(m.group(1)) if m else 30


def schedule(inv: FpInvoice, terms: str | None, today: date) -> dict[str, Any]:
    """Due date, and the early-pay discount if it can still be taken today."""
    start = inv.invoice_date or today
    due = inv.due_date or start + timedelta(days=net_days(terms))
    disc = discount_terms(terms)
    discount, until = Decimal("0"), None
    if disc and inv.total:
        until = start + timedelta(days=disc[1])
        if today <= until:
            discount = (inv.total * disc[0] / 100).quantize(CENT)
    return {"due": due, "discount": discount, "discount_until": until}


async def _bank(session: AsyncSession, vendor_code: str) -> FpVendorBankAccount | None:
    return await session.scalar(
        select(FpVendorBankAccount)
        .where(
            FpVendorBankAccount.vendor_code == vendor_code, FpVendorBankAccount.retired_at.is_(None)
        )
        .order_by(FpVendorBankAccount.created_at.desc())
        .limit(1)
    )


def _flag(key: str, label: str, severity: str) -> dict[str, str]:
    return {"key": key, "label": label, "severity": severity}  # block / review / info


async def _risk(
    session: AsyncSession,
    inv: FpInvoice,
    amount: Decimal,
    bank: FpVendorBankAccount | None,
    settings: Any,
    today: date,
    due: date,
) -> tuple[list[dict[str, str]], CallbackStatus]:
    flags: list[dict[str, str]] = []
    callback = CallbackStatus.NOT_NEEDED
    if bank is None:
        flags.append(_flag("no_bank", "No verified bank account on file", "block"))
    else:
        changed = (utcnow() - bank.created_at).days <= settings.bank_change_days
        earlier = await session.scalar(
            select(FpVendorBankAccount.id).where(
                FpVendorBankAccount.vendor_code == inv.vendor_code,
                FpVendorBankAccount.retired_at.is_not(None),
            )
        )
        if changed:
            flags.append(
                _flag(
                    "bank_change",
                    f"Bank details {'changed' if earlier else 'set up'} "
                    f"{(utcnow() - bank.created_at).days} days ago: call back before paying",
                    "block",
                )
            )
            callback = CallbackStatus.NEEDED
    if amount >= settings.unusual_payment_amount:
        flags.append(
            _flag(
                "large",
                f"Large payment (at or over {settings.unusual_payment_amount:,.2f})",
                "review",
            )
        )
    paid = list(
        await session.scalars(
            select(FpInvoice.total).where(
                FpInvoice.vendor_code == inv.vendor_code, FpInvoice.status == InvoiceStatus.PAID
            )
        )
    )
    if not paid:
        flags.append(_flag("first_payment", "First payment to this vendor", "review"))
    elif len(paid) >= 2:
        avg = sum((p or 0 for p in paid), Decimal("0")) / len(paid)
        if avg > 0 and amount > avg * 3:
            flags.append(
                _flag(
                    "unusual_amount",
                    f"Over three times this vendor's average payment ({avg:,.2f})",
                    "review",
                )
            )
    since = utcnow() - timedelta(days=DUPLICATE_PAYMENT_DAYS)
    twin = await session.scalar(
        select(FpInvoice.id).where(
            FpInvoice.vendor_code == inv.vendor_code,
            FpInvoice.id != inv.id,
            FpInvoice.total == inv.total,
            FpInvoice.status == InvoiceStatus.PAID,
            FpInvoice.paid_at >= since,
        )
    )
    if twin:
        flags.append(
            _flag(
                "same_amount_paid",
                f"Same vendor and amount paid in the last {DUPLICATE_PAYMENT_DAYS} days",
                "review",
            )
        )
    if due < today:
        flags.append(_flag("overdue", f"Overdue since {due.isoformat()}", "info"))
    return flags, callback


async def propose(
    session: AsyncSession, access: FinanceAccess, ctx: RequestContext
) -> FpPaymentRun:
    """The payment agent's proposed run: approved invoices due within the horizon or with a
    discount still to take, grouped by currency and bank, with the risk checks."""
    settings = await current_settings(session)
    today = utcnow().date()
    horizon = today + timedelta(days=settings.payment_horizon_days)
    in_runs = set(
        await session.scalars(
            select(FpPaymentItem.invoice_id)
            .join(FpPaymentRun, FpPaymentRun.id == FpPaymentItem.run_id)
            .where(FpPaymentRun.status.in_(LIVE_RUNS), FpPaymentItem.excluded.is_(False))
        )
    )
    candidates = [
        i
        for i in await session.scalars(
            select(FpInvoice)
            .where(FpInvoice.status == InvoiceStatus.READY)
            .order_by(FpInvoice.invoice_date)
        )
        if i.id not in in_runs and i.vendor_code and i.total
    ]
    items: list[FpPaymentItem] = []
    for inv in candidates:
        po = await session.get(FpPurchaseOrder, inv.po_id) if inv.po_id else None
        # The PO's terms govern; an invoice without a PO goes by the terms printed on it
        terms = po.payment_terms if po else (inv.extraction or {}).get("payment_terms")
        sched = schedule(inv, terms, today)
        if sched["due"] > horizon and not sched["discount"]:
            continue  # not due yet, no discount to take: a later run
        assert inv.total is not None  # noqa: S101 - filtered above
        amount = inv.total - sched["discount"]
        bank = await _bank(session, inv.vendor_code or "")
        flags, callback = await _risk(session, inv, amount, bank, settings, today, sched["due"])
        reason = "discount" if sched["discount"] else "overdue" if sched["due"] < today else "due"
        items.append(
            FpPaymentItem(
                position=len(items) + 1,
                invoice_id=inv.id,
                vendor_code=inv.vendor_code or "",
                vendor_name=inv.vendor_name or "",
                currency=inv.currency,
                bank_name=bank.bank_name if bank else None,
                account_last4=bank.account_last4 if bank else None,
                group_key=f"{inv.currency} · {bank.bank_name if bank else 'no bank account'}",
                invoice_total=inv.total,
                discount=sched["discount"],
                amount=amount,
                due_date=sched["due"],
                discount_until=sched["discount_until"],
                reason=reason,
                flags=flags,
                callback_status=callback,
                excluded=bank is None,
                exclude_reason="No verified bank account: onboard the vendor's bank first"
                if bank is None
                else None,
            )
        )
    if not items:
        raise PaymentInvalidError(
            f"Nothing to pay: no approved invoice is due within "
            f"{settings.payment_horizon_days} days or has a discount to take."
        )
    run = FpPaymentRun(
        status=RunStatus.PROPOSED,
        run_date=today,
        horizon_days=settings.payment_horizon_days,
        cash_available=settings.cash_available,
        proposed_by=access.user.id,
        items=items,
    )
    session.add(run)
    await session.flush()
    payable = [i for i in items if not i.excluded]
    total = sum((i.amount for i in payable), Decimal("0"))
    disc = sum((i.discount for i in payable), Decimal("0"))
    record_event(
        session,
        "fpod.payment_run_proposed",
        ctx,
        actor_id=None,
        run=run.reference,
        summary=f"Payment agent proposed {run.reference}: {len(payable)} invoice(s), "
        f"{total:,.2f}"
        + (f", discounts {disc:,.2f}" if disc else "")
        + f"; {sum(1 for i in items if i.flags)} with risk flags",
    )
    await session.commit()
    return run


# --- reading ---------------------------------------------------------------------------------


async def _load(session: AsyncSession, run_id: uuid.UUID, *, lock: bool = False) -> FpPaymentRun:
    run = await session.get(FpPaymentRun, run_id, with_for_update=lock)
    if run is None:
        raise PaymentNotFoundError("Payment run not found.")
    return run


def _payable(run: FpPaymentRun) -> list[FpPaymentItem]:
    return [i for i in run.items if not i.excluded]


def release_blockers(run: FpPaymentRun) -> list[str]:
    """Why the run can't be released yet (none: it can)."""
    out = []
    payable = _payable(run)
    if not payable:
        out.append("No payments left in the run.")
    pending = [i for i in payable if i.callback_status == CallbackStatus.NEEDED]
    if pending:
        out.append(
            f"{len(pending)} payment(s) to changed bank details need the analyst's call-back: "
            + ", ".join(sorted({i.vendor_name for i in pending}))
        )
    blocked = [
        i
        for i in payable
        if any(f["severity"] == "block" and f["key"] != "bank_change" for f in i.flags)
    ]
    if blocked:
        out.append(f"{len(blocked)} payment(s) have blocking flags: exclude them.")
    by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for i in payable:
        by_currency[i.currency] += i.amount
    settings_cash = run.cash_available
    if settings_cash is not None:
        for cur, total in by_currency.items():
            if total > settings_cash:
                out.append(
                    f"{cur} {total:,.2f} is more than the cash available ({settings_cash:,.2f})."
                )
    return out


async def detail(session: AsyncSession, run_id: uuid.UUID, viewer: User) -> dict[str, Any]:
    run = await _load(session, run_id)
    approvals = list(
        await session.scalars(
            select(FpPaymentApproval)
            .where(FpPaymentApproval.run_id == run.id)
            .order_by(FpPaymentApproval.created_at)
        )
    )
    ids = {
        run.proposed_by,
        *(a.user_id for a in approvals),
        *(i.callback_by for i in run.items if i.callback_by),
    }
    names = dict(
        (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all()
    )
    invoices = {
        i.id: i
        for i in await session.scalars(
            select(FpInvoice).where(FpInvoice.id.in_([x.invoice_id for x in run.items]))
        )
    }
    groups: dict[str, dict[str, Any]] = {}
    for i in _payable(run):
        g = groups.setdefault(
            i.group_key,
            {
                "key": i.group_key,
                "currency": i.currency,
                "count": 0,
                "total": Decimal("0"),
                "discount": Decimal("0"),
            },
        )
        g["count"] += 1
        g["total"] += i.amount
        g["discount"] += i.discount
    blockers = release_blockers(run)
    can_approve = None
    if run.status not in LIVE_RUNS:
        can_approve = f"{run.reference} is {run.status.value}."
    elif blockers:
        can_approve = blockers[0]
    elif any(a.user_id == viewer.id for a in approvals):
        can_approve = "You gave the first release: a second person gives the other."
    return {
        "id": run.id,
        "reference": run.reference,
        "status": run.status,
        "version": run.version,
        "run_date": run.run_date,
        "horizon_days": run.horizon_days,
        "cash_available": run.cash_available,
        "proposed_by_name": names.get(run.proposed_by),
        "created_at": run.created_at,
        "released_at": run.released_at,
        "cancelled_reason": run.cancelled_reason,
        "groups": [
            {**g, "total": str(g["total"]), "discount": str(g["discount"])} for g in groups.values()
        ],
        "total": str(sum((i.amount for i in _payable(run)), Decimal("0"))),
        "discounts": str(sum((i.discount for i in _payable(run)), Decimal("0"))),
        "items": [
            {
                "id": i.id,
                "position": i.position,
                "invoice_id": i.invoice_id,
                "invoice_reference": invoices[i.invoice_id].reference
                if i.invoice_id in invoices
                else None,
                "vendor_invoice_number": invoices[i.invoice_id].vendor_invoice_number
                if i.invoice_id in invoices
                else None,
                "vendor_code": i.vendor_code,
                "vendor_name": i.vendor_name,
                "currency": i.currency,
                "bank_name": i.bank_name,
                "account_last4": i.account_last4,
                "group_key": i.group_key,
                "invoice_total": str(i.invoice_total),
                "discount": str(i.discount),
                "amount": str(i.amount),
                "due_date": i.due_date,
                "discount_until": i.discount_until,
                "reason": i.reason,
                "flags": i.flags,
                "callback_status": i.callback_status,
                "callback_note": i.callback_note,
                "callback_by_name": names.get(i.callback_by) if i.callback_by else None,
                "callback_at": i.callback_at,
                "excluded": i.excluded,
                "exclude_reason": i.exclude_reason,
                "payment_ref": i.payment_ref,
            }
            for i in run.items
        ],
        "approvals": [
            {
                "name": names.get(a.user_id),
                "note": a.note,
                "at": a.created_at,
                "self_approval": a.self_approval,
            }
            for a in approvals
        ],
        "release_blockers": blockers,
        "can_approve": can_approve,
    }


async def list_runs(session: AsyncSession) -> list[dict[str, Any]]:
    runs = await session.scalars(select(FpPaymentRun).order_by(FpPaymentRun.number.desc()))
    return [
        {
            "id": r.id,
            "reference": r.reference,
            "status": r.status,
            "run_date": r.run_date,
            "count": len(_payable(r)),
            "total": str(sum((i.amount for i in _payable(r)), Decimal("0"))),
            "discounts": str(sum((i.discount for i in _payable(r)), Decimal("0"))),
            "flags": sum(1 for i in _payable(r) if i.flags),
            "created_at": r.created_at,
            "released_at": r.released_at,
        }
        for r in runs
    ]


# --- people: exclude, call back, release -------------------------------------------------------


async def _item(session: AsyncSession, run: FpPaymentRun, item_id: uuid.UUID) -> FpPaymentItem:
    item = next((i for i in run.items if i.id == item_id), None)
    if item is None:
        raise PaymentNotFoundError("Payment not found in this run.")
    return item


def _editable(run: FpPaymentRun, version: int) -> None:
    if run.version != version:
        raise PaymentStateError("Someone changed this run since you opened it. Reload it.")
    if run.status != RunStatus.PROPOSED:
        raise PaymentStateError(
            f"{run.reference} is {run.status.value.replace('_', ' ')}: it can't be changed "
            "(cancel it and let the agent propose again)."
        )


async def set_excluded(
    session: AsyncSession,
    access: FinanceAccess,
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    version: int,
    excluded: bool,
    reason: str,
    ctx: RequestContext,
) -> None:
    run = await _load(session, run_id, lock=True)
    _editable(run, version)
    item = await _item(session, run, item_id)
    if not excluded and item.bank_name is None:
        raise PaymentInvalidError("No verified bank account: it can't be paid.")
    item.excluded, item.exclude_reason = excluded, (reason.strip() or None) if excluded else None
    run.version += 1
    record_event(
        session,
        "fpod.payment_item_" + ("excluded" if excluded else "included"),
        ctx,
        actor_id=access.user.id,
        run=run.reference,
        summary=f"{'Took' if excluded else 'Put'} {item.vendor_name} {item.amount:,.2f} "
        f"{'out of' if excluded else 'back in'} {run.reference}"
        + (f": {reason}" if excluded and reason else ""),
    )
    await session.commit()


class CallbackIn(BaseModel):
    expected_version: int
    phone: str = Field(min_length=5, max_length=40)
    source: str = Field(min_length=3, max_length=120)
    contact: str = Field(min_length=2, max_length=200)
    confirmed_last4: str = Field(pattern=r"^\d{4}$")
    note: str = Field(default="", max_length=2000)


async def confirm_callback(
    session: AsyncSession,
    access: FinanceAccess,
    run_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CallbackIn,
    ctx: RequestContext,
) -> None:
    """The analyst called the vendor on a number we already hold and confirmed the account."""
    run = await _load(session, run_id, lock=True)
    _editable(run, body.expected_version)
    item = await _item(session, run, item_id)
    if item.callback_status != CallbackStatus.NEEDED:
        raise PaymentStateError("No call-back is needed for this payment.")
    if body.confirmed_last4 != item.account_last4:
        raise PaymentInvalidError(
            "The account the vendor confirmed doesn't match the one on file: don't pay. "
            "Exclude it and start a bank-change check."
        )
    item.callback_status = CallbackStatus.CONFIRMED
    item.callback_by, item.callback_at = access.user.id, utcnow()
    item.callback_note = (
        f"Called {body.phone} ({body.source}), spoke to {body.contact}; "
        f"account ending {body.confirmed_last4} confirmed. {body.note}"
    ).strip()
    run.version += 1
    record_event(
        session,
        "fpod.payment_callback",
        ctx,
        actor_id=access.user.id,
        run=run.reference,
        summary=f"Call-back before paying {item.vendor_name}: {item.callback_note}",
    )
    await session.commit()


async def approve(
    session: AsyncSession,
    access: FinanceAccess,
    run_id: uuid.UUID,
    version: int,
    note: str,
    ctx: RequestContext,
) -> FpPaymentRun:
    """Treasury's release. The second, by a different person, releases the run; then the
    vendor agent posts and remits. Nothing else releases a payment."""
    run = await _load(session, run_id, lock=True)
    if run.version != version:
        raise PaymentStateError("Someone changed this run since you opened it. Reload it.")
    if run.status not in LIVE_RUNS:
        raise PaymentStateError(f"{run.reference} is {run.status.value}.")
    blockers = release_blockers(run)
    if blockers:
        raise PaymentInvalidError("Not yet: " + " ".join(blockers))
    approvals = list(
        await session.scalars(select(FpPaymentApproval).where(FpPaymentApproval.run_id == run.id))
    )
    self_approval = False
    if approvals:  # the second release: never the first releaser (unless allowed, marked)
        self_approval = await check_different_person(
            session,
            access.user,
            approvals[0].user_id,
            "Two different people release every payment run.",
        )
    session.add(
        FpPaymentApproval(
            run_id=run.id, user_id=access.user.id, note=note.strip(), self_approval=self_approval
        )
    )
    run.version += 1
    total = sum((i.amount for i in _payable(run)), Decimal("0"))
    if not approvals:
        run.status = RunStatus.PARTLY_APPROVED
        record_event(
            session,
            "fpod.payment_run_approved",
            ctx,
            actor_id=access.user.id,
            run=run.reference,
            summary=f"First release of {run.reference} ({total:,.2f}); a second "
            "person releases it" + (f": {note.strip()}" if note.strip() else ""),
        )
        await session.commit()
        return run
    run.status, run.released_at = RunStatus.RELEASED, utcnow()
    record_event(
        session,
        "fpod.payment_run_released",
        ctx,
        actor_id=access.user.id,
        run=run.reference,
        self_approval=self_approval,
        summary=f"Second release: {run.reference} ({total:,.2f}) released"
        + (" (same person: self-approval allowed)" if self_approval else ""),
    )
    await session.flush()
    await _post_and_remit(session, run, access.user, ctx)
    await session.commit()
    return run


async def _post_and_remit(
    session: AsyncSession, run: FpPaymentRun, actor: User, ctx: RequestContext
) -> None:
    """The vendor agent: invoices marked paid, a remittance advice to each vendor."""
    by_vendor: dict[str, list[tuple[FpPaymentItem, FpInvoice]]] = defaultdict(list)
    for n, item in enumerate(_payable(run), start=1):
        inv = await session.get(FpInvoice, item.invoice_id, with_for_update=True)
        assert inv is not None  # noqa: S101 - RESTRICT
        item.payment_ref = f"{run.reference}-{n:03d}"
        inv.status, inv.paid_at, inv.payment_ref = InvoiceStatus.PAID, utcnow(), item.payment_ref
        inv.version += 1
        by_vendor[item.vendor_code].append((item, inv))
    org = get_settings().email_sender_name
    for code, rows in by_vendor.items():
        vendor = await session.scalar(select(FpVendor).where(FpVendor.code == code))
        if vendor is None or not vendor.email:
            continue
        lines = "\n".join(
            f"  Invoice {inv.vendor_invoice_number or inv.reference}: "
            + (
                f"{item.invoice_total:,.2f} less early-payment discount {item.discount:,.2f}"
                f" = {item.amount:,.2f} {item.currency}"
                if item.discount
                else f"{item.amount:,.2f} {item.currency}"
            )
            + f"  (payment reference {item.payment_ref})"
            for item, inv in rows
        )
        total = sum((item.amount for item, _ in rows), Decimal("0"))
        last4 = rows[0][0].account_last4
        body = (
            f"Hello {vendor.name},\n\nWe have paid the following invoices today "
            f"to your account ending {last4}:\n\n{lines}\n\nTotal: {total:,.2f} "
            f"{rows[0][0].currency}\n\nThank you,\n{org}"
        )
        sent = await mail.send(
            session,
            kind=mail.MailKind.REMITTANCE,
            to_email=vendor.email,
            to_name=vendor.name,
            subject=f"Remittance advice from {org}",
            body=body,
            sent_by=actor.id,
        )
        record_event(
            session,
            "fpod.remittance_sent",
            ctx,
            actor_id=None,
            run=run.reference,
            summary=f"Vendor agent marked {len(rows)} invoice(s) paid and sent "
            f"{vendor.name} a remittance ({total:,.2f}){mail.outcome(sent)}",
        )


async def cancel(
    session: AsyncSession,
    access: FinanceAccess,
    run_id: uuid.UUID,
    version: int,
    reason: str,
    ctx: RequestContext,
) -> None:
    run = await _load(session, run_id, lock=True)
    if run.version != version:
        raise PaymentStateError("Someone changed this run since you opened it. Reload it.")
    if run.status not in LIVE_RUNS:
        raise PaymentStateError(f"{run.reference} is {run.status.value}: it can't be cancelled.")
    run.status, run.cancelled_reason = RunStatus.CANCELLED, reason.strip()
    run.version += 1
    record_event(
        session,
        "fpod.payment_run_cancelled",
        ctx,
        actor_id=access.user.id,
        run=run.reference,
        summary=f"Cancelled {run.reference}: {reason.strip()}",
    )
    await session.commit()


async def delete_runs(
    session: AsyncSession, access: FinanceAccess, ids: list[uuid.UUID], ctx: RequestContext
) -> int:
    """Remove payment runs (e.g. to run a demo again). Invoices a released run paid go back to
    ready to pay, so the payment agent picks them up again; remittances already emailed stay
    sent. The audit trail keeps a record of each run."""
    runs = list(
        await session.scalars(
            select(FpPaymentRun).where(FpPaymentRun.id.in_(ids)).with_for_update()
        )
    )
    if not runs:
        raise PaymentNotFoundError("Payment run not found.")
    for run in runs:
        refs = {i.payment_ref for i in run.items if i.payment_ref}
        reopened = 0
        for inv in await session.scalars(
            select(FpInvoice).where(
                FpInvoice.id.in_([i.invoice_id for i in run.items]),
                FpInvoice.status == InvoiceStatus.PAID,
            )
        ):
            if inv.payment_ref in refs:
                inv.status, inv.paid_at, inv.payment_ref = InvoiceStatus.READY, None, None
                inv.version += 1
                reopened += 1
        record_event(
            session,
            "fpod.payment_run_deleted",
            ctx,
            actor_id=access.user.id,
            run=run.reference,
            status=run.status.value,
            total=str(sum((i.amount for i in run.items if not i.excluded), Decimal("0"))),
            summary=f"Deleted {run.reference} (was {run.status.value}, {len(run.items)} "
            f"payments)" + (f"; {reopened} invoice(s) back to ready to pay" if reopened else ""),
        )
        await session.delete(run)
    await session.commit()
    return len(runs)


async def bank_file(session: AsyncSession, run_id: uuid.UUID) -> tuple[str, bytes]:
    """The released run as a CSV for the bank portal (where treasury's dual approval is
    repeated). Full account numbers: only after release."""
    run = await _load(session, run_id)
    if run.status != RunStatus.RELEASED:
        raise PaymentStateError("The bank file is available once the run is released.")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "payment_ref",
            "group",
            "vendor_code",
            "vendor_name",
            "bank",
            "routing_number",
            "account_number",
            "currency",
            "amount",
            "invoice",
        ]
    )
    for item in _payable(run):
        bank = await _bank(session, item.vendor_code)
        inv = await session.get(FpInvoice, item.invoice_id)
        w.writerow(
            [
                item.payment_ref,
                item.group_key,
                item.vendor_code,
                item.vendor_name,
                item.bank_name,
                crypto.decrypt(bank.routing_number_enc) if bank else "",
                crypto.decrypt(bank.account_number_enc) if bank else "",
                item.currency,
                f"{item.amount:.2f}",
                inv.vendor_invoice_number if inv else "",
            ]
        )
    return f"{run.reference}-bank-file.csv", out.getvalue().encode()


# --- vendor queries: the vendor agent answers, analysts take disputes --------------------------

QUERY_PROMPT_VERSION = "fpod_vendor_query/v1"
QUERY_SYSTEM = """\
You sort a supplier's question to an accounts payable team. Choose the intent:
- status: they ask whether, when or how an invoice was or will be paid
- missing_invoice: they ask whether we received an invoice
- dispute: they disagree (short payment, deduction, rejection, wrong amount, late fee)
- other: anything else
Also give the invoice number they mention, exactly as written, or null.
"""


class QueryRead(BaseModel):
    intent: QueryIntent
    invoice_number: str | None


_DISPUTE = re.compile(
    r"\b(short|deduct|dispute|disagree|wrong|underpaid|incorrect|reject|"
    r"late fee|penalt|complain)",
    re.IGNORECASE,
)
_MISSING = re.compile(r"\b(receiv|got my|did you get|arrive)", re.IGNORECASE)


def _keywords(question: str) -> QueryIntent:
    if _DISPUTE.search(question):
        return QueryIntent.DISPUTE
    if _MISSING.search(question):
        return QueryIntent.MISSING_INVOICE
    if re.search(r"\b(pa(id|y)|payment|when|status|remit)", question, re.IGNORECASE):
        return QueryIntent.STATUS
    return QueryIntent.OTHER


async def _classify(llm: LLMProvider, question: str) -> tuple[QueryIntent, str | None, str]:
    try:
        r = await ai.extract(
            llm,
            system=QUERY_SYSTEM,
            user=question,
            schema=QueryRead,
            prompt_version=QUERY_PROMPT_VERSION,
            validate=lambda q: (
                []
                if not q.invoice_number or q.invoice_number.lower() in question.lower()
                else ["the invoice number isn't in the question"]
            ),
        )
    except (LLMError, ai.AiOutputRejectedError):
        return _keywords(question), None, "keywords"
    return r.output.intent, r.output.invoice_number, "ai"


def status_answer(
    inv: FpInvoice, exc: FpInvoiceException | None, in_run: FpPaymentRun | None
) -> str:
    """What the records say about one invoice, in plain words (facts only)."""
    ref = inv.vendor_invoice_number or inv.reference
    if inv.status == InvoiceStatus.PAID:
        when = inv.paid_at.date().isoformat() if inv.paid_at else "?"
        return f"Your invoice {ref} was paid on {when} (payment reference {inv.payment_ref})."
    if inv.status == InvoiceStatus.READY:
        if in_run is not None:
            return (
                f"Your invoice {ref} is approved and in our payment run of "
                f"{in_run.run_date.isoformat()}; you'll get a remittance advice when it's paid."
            )
        return (
            f"Your invoice {ref} is approved for payment; it will be paid by its due date"
            f"{f' ({inv.due_date.isoformat()})' if inv.due_date else ''}."
        )
    if inv.status == InvoiceStatus.EXCEPTION:
        why = {
            "price": "the price differs from our order",
            "quantity": "the quantity is more than we've received",
            "no_receipt": "we're confirming the delivery",
            "not_on_po": "a line isn't on our order",
            "no_po": "we can't find our purchase order for it",
            "vendor": "it quotes an order with another supplier",
            "header": "its totals don't add up",
        }
        reasons = ", ".join(why.get(k, k) for k in (exc.kinds if exc else []))
        extra = (
            " We've asked you for a credit note."
            if exc and exc.status == ExceptionStatus.WAITING_VENDOR
            else ""
        )
        return f"Your invoice {ref} is on hold: {reasons or 'it is being checked'}.{extra}"
    if inv.status == InvoiceStatus.REJECTED:
        return f"Your invoice {ref} was rejected: {inv.rejected_reason or 'see our earlier email'}."
    if inv.status == InvoiceStatus.DUPLICATE:
        return f"We have {ref} already; this copy was set aside as a duplicate."
    return f"We received your invoice {ref} and are checking it."


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"


async def ask(
    session: AsyncSession,
    *,
    from_email: str,
    invoice_number: str | None,
    question: str,
    via: str,
    llm: LLMProvider,
    ctx: RequestContext,
    actor: User | None = None,
) -> FpVendorQuery:
    """A vendor's question. The vendor agent answers status and missing-invoice questions from
    the records, by email to the address on file only; disputes go to an analyst."""
    from_email = from_email.strip().lower()
    intent, read_number, source = await _classify(llm, question)
    number = (invoice_number or "").strip() or read_number
    vendor = next(
        iter(
            await session.scalars(select(FpVendor).where(FpVendor.email.ilike(from_email)).limit(1))
        ),
        None,
    )
    q = FpVendorQuery(
        via=via,
        from_email=from_email,
        vendor_code=vendor.code if vendor else None,
        vendor_name=vendor.name if vendor else None,
        invoice_number=number,
        question=question.strip(),
        intent=intent,
        intent_source=source,
        status=QueryStatus.ESCALATED,
    )
    session.add(q)
    await session.flush()
    answer, reason = None, None
    if vendor is None:
        reason = "The email isn't one we hold for a vendor: an analyst checks who's asking."
    elif intent in (QueryIntent.DISPUTE, QueryIntent.OTHER):
        reason = (
            "A dispute: an analyst handles it."
            if intent == QueryIntent.DISPUTE
            else "Not a status question: an analyst answers."
        )
    else:
        inv = None
        if number:
            key = invoice_agents._norm_number(number)
            inv = next(
                (
                    i
                    for i in await session.scalars(
                        select(FpInvoice).where(FpInvoice.vendor_code == vendor.code)
                    )
                    if invoice_agents._norm_number(i.vendor_invoice_number) == key
                ),
                None,
            )
        if inv is None and number:
            answer = (
                f"We have no invoice {number} from you on record. Please send it to us "
                "quoting our purchase order number."
            )
        elif inv is None:
            reason = "No invoice number given: an analyst looks it up."
        else:
            q.invoice_id = inv.id
            exc = await session.scalar(
                select(FpInvoiceException)
                .where(FpInvoiceException.invoice_id == inv.id)
                .order_by(FpInvoiceException.created_at.desc())
                .limit(1)
            )
            in_run = await session.scalar(
                select(FpPaymentRun)
                .join(FpPaymentItem, FpPaymentItem.run_id == FpPaymentRun.id)
                .where(
                    FpPaymentItem.invoice_id == inv.id,
                    FpPaymentItem.excluded.is_(False),
                    FpPaymentRun.status.in_(LIVE_RUNS),
                )
                .limit(1)
            )
            answer = status_answer(inv, exc, in_run)
    if answer is not None and vendor is not None and vendor.email:
        q.answer, q.status, q.answered_at = answer, QueryStatus.ANSWERED, utcnow()
        org = get_settings().email_sender_name
        await mail.send(
            session,
            kind=mail.MailKind.QUERY_ANSWER,
            to_email=vendor.email,
            to_name=vendor.name,
            subject=f"Re: your question to {org} ({q.reference})",
            body=f"Hello {vendor.name},\n\n{answer}\n\nThank you,\n{org}",
            sent_by=actor.id if actor else await _system_user(session),
        )
    else:
        q.escalation_reason = reason
    record_event(
        session,
        "fpod.vendor_query",
        ctx,
        actor_id=actor.id if actor else None,
        run=q.reference,
        summary=f"Vendor agent: {q.reference} from {_mask(from_email)} "
        f"({intent.value}, by {source})"
        + (
            " answered from the records"
            if q.status == QueryStatus.ANSWERED
            else f" escalated: {reason}"
        ),
    )
    await session.commit()
    return q


async def _system_user(session: AsyncSession) -> uuid.UUID:
    """Mail the vendor agent sends on its own is logged against the first Finance Admin."""
    user_id = await session.scalar(
        select(User.id)
        .where(User.role == UserRole.FINANCE_ADMIN)
        .order_by(User.created_at)
        .limit(1)
    )
    assert user_id is not None  # noqa: S101 - the Finance POD needs a Finance Admin
    return user_id


async def reply(
    session: AsyncSession,
    access: FinanceAccess,
    query_id: uuid.UUID,
    answer: str,
    ctx: RequestContext,
) -> FpVendorQuery:
    """The analyst answers an escalated query (disputes, escalations)."""
    q = await session.get(FpVendorQuery, query_id, with_for_update=True)
    if q is None:
        raise PaymentNotFoundError("Query not found.")
    if q.status != QueryStatus.ESCALATED:
        raise PaymentStateError(f"{q.reference} is already {q.status.value}.")
    vendor = (
        await session.scalar(select(FpVendor).where(FpVendor.code == q.vendor_code))
        if q.vendor_code
        else None
    )
    to = vendor.email if vendor and vendor.email else q.from_email
    org = get_settings().email_sender_name
    sent = await mail.send(
        session,
        kind=mail.MailKind.QUERY_ANSWER,
        to_email=to,
        to_name=q.vendor_name,
        subject=f"Re: your question to {org} ({q.reference})",
        body=f"Hello {q.vendor_name or ''},\n\n{answer.strip()}\n\nThank you,\n{org}",
        sent_by=access.user.id,
    )
    q.answer, q.status = answer.strip(), QueryStatus.RESOLVED
    q.answered_by, q.answered_at = access.user.id, utcnow()
    record_event(
        session,
        "fpod.vendor_query_answered",
        ctx,
        actor_id=access.user.id,
        run=q.reference,
        summary=f"Analyst answered {q.reference}{mail.outcome(sent)}",
    )
    await session.commit()
    return q


async def list_queries(session: AsyncSession, status: QueryStatus | None) -> list[dict[str, Any]]:
    query = select(FpVendorQuery).order_by(FpVendorQuery.number.desc())
    if status is not None:
        query = query.where(FpVendorQuery.status == status)
    names = dict((await session.execute(select(User.id, User.full_name))).all())
    return [
        {
            "id": q.id,
            "reference": q.reference,
            "via": q.via,
            "from_email": q.from_email,
            "vendor_code": q.vendor_code,
            "vendor_name": q.vendor_name,
            "invoice_number": q.invoice_number,
            "invoice_id": q.invoice_id,
            "question": q.question,
            "intent": q.intent,
            "intent_source": q.intent_source,
            "status": q.status,
            "answer": q.answer,
            "answered_by_name": names.get(q.answered_by)
            if q.answered_by
            else ("Vendor agent" if q.status == QueryStatus.ANSWERED else None),
            "answered_at": q.answered_at,
            "escalation_reason": q.escalation_reason,
            "created_at": q.created_at,
            "response_minutes": round((q.answered_at - q.created_at).total_seconds() / 60, 1)
            if q.answered_at
            else None,
        }
        for q in await session.scalars(query)
    ]


# --- measures ------------------------------------------------------------------------------------


async def measures(session: AsyncSession) -> dict[str, Any]:
    items = list(
        await session.scalars(
            select(FpPaymentItem)
            .join(FpPaymentRun, FpPaymentRun.id == FpPaymentItem.run_id)
            .where(FpPaymentRun.status == RunStatus.RELEASED, FpPaymentItem.excluded.is_(False))
        )
    )
    runs = {r.id: r for r in await session.scalars(select(FpPaymentRun))}
    released = {k: r.released_at.date() for k, r in runs.items() if r.released_at}
    on_time = sum(1 for i in items if i.run_id in released and released[i.run_id] <= i.due_date)
    taken = sum((i.discount for i in items), Decimal("0"))
    missed = [i for i in items if i.discount == 0 and i.discount_until is not None]
    queries = list(await session.scalars(select(FpVendorQuery)))
    times = [(q.answered_at - q.created_at).total_seconds() / 60 for q in queries if q.answered_at]
    return {
        "payments": len(items),
        "on_time": on_time,
        "on_time_rate": round(on_time / len(items), 3) if items else None,
        "discounts_captured": str(taken),
        "discounts_taken_count": sum(1 for i in items if i.discount > 0),
        "discounts_missed_count": len(missed),
        "queries": len(queries),
        "queries_answered_by_agent": sum(
            1 for q in queries if q.answered_by is None and q.answered_at
        ),
        "queries_open": sum(1 for q in queries if q.status == QueryStatus.ESCALATED),
        "median_response_minutes": round(median(times), 1) if times else None,
    }
