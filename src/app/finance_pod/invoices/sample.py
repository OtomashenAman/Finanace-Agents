"""Sample supplier invoices for demos and testing: a PDF written from a real PO, so the
capture agent reads it exactly as it reads an uploaded one.

Scenarios: `match` (what was received, at the PO prices), `price` (a line above the
price tolerance), `quantity` (more than was received), `duplicate` (the same number and
amount as the last invoice for the PO).
"""

import random
import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.finance_pod import pdf
from src.app.finance_pod.invoices.models import FpInvoice, FpReceipt
from src.app.finance_pod.orders.models import FpPurchaseOrder

Scenario = Literal["match", "price", "quantity", "duplicate"]
CENT = Decimal("0.01")


async def received(session: AsyncSession, po: FpPurchaseOrder) -> dict[int, Decimal]:
    """What was received so far, per PO line position."""
    out: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for receipt in await session.scalars(select(FpReceipt).where(FpReceipt.po_id == po.id)):
        for ln in receipt.lines:
            out[ln.po_line] += ln.quantity
    return out


def _number(po: FpPurchaseOrder) -> str:
    prefix = re.sub(r"[^A-Z]", "", po.vendor_name.upper())[:3] or "INV"
    return f"{prefix}-{random.randint(10000, 99999)}"  # noqa: S311 - a demo number, not a secret


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}" if value == value.to_integral_value() else f"{value:f}"


async def build(
    session: AsyncSession, po: FpPurchaseOrder, scenario: Scenario
) -> tuple[str, bytes, str]:
    """The sample invoice: (filename, PDF, what makes it this scenario)."""
    got = await received(session, po)
    note = "Billed what was received, at the PO prices: it should match."
    number = _number(po)
    lines: list[tuple[str, Decimal, Decimal]] = []
    for ln in po.lines:
        qty = got.get(ln.position) or ln.quantity
        lines.append((ln.description, qty, ln.unit_price))
    if not got:
        note = "Nothing is received on this PO yet: expect a missing-receipt exception."
    if scenario == "price" and lines:
        desc, qty, price = lines[0]
        lines[0] = (desc, qty, (price * Decimal("1.08")).quantize(CENT))
        note = f"Line 1 billed 8% above the PO price ({price:,.2f}): expect a price variance."
    elif scenario == "quantity" and lines:
        desc, qty, price = lines[0]
        lines[0] = (desc, qty + 2, price)
        note = f"Line 1 bills {_qty(qty + 2)}, 2 more than received: expect a quantity variance."
    elif scenario == "duplicate":
        last = await session.scalar(
            select(FpInvoice)
            .where(FpInvoice.po_id == po.id, FpInvoice.vendor_invoice_number.is_not(None))
            .order_by(FpInvoice.created_at.desc())
            .limit(1)
        )
        if last is not None and last.vendor_invoice_number:
            number = last.vendor_invoice_number
            lines = [(ln.description, ln.quantity, ln.unit_price) for ln in last.lines] or lines
            note = (
                f"Same number ({number}) and amount as {last.reference}: expect the "
                "duplicate guard."
            )
        else:
            note = "No earlier invoice for this PO to duplicate: this one matches instead."

    today = utcnow().date()
    days = re.search(r"net\s*(\d+)", po.payment_terms or "", re.IGNORECASE)
    due = today + timedelta(days=int(days.group(1)) if days else 30)
    subtotal = sum(((q * p).quantize(CENT) for _, q, p in lines), Decimal("0"))
    org = get_settings().email_sender_name
    rows: list[pdf.Line] = [
        (po.vendor_name, 16, True),
        ("INVOICE", 13, True),
        ("", 6, False),
        (f"Invoice number: {number}", 10, False),
        (f"Invoice date: {today.isoformat()}", 10, False),
        (f"Due date: {due.isoformat()}", 10, False),
        (f"Payment terms: {po.payment_terms or 'Net 30'}", 10, False),
        (f"Bill to: {org}", 10, False),
        (f"Purchase order: {po.reference}", 10, True),
        ("", 6, False),
        ("Line | Description | Quantity | Unit price | Amount", 9, True),
    ]
    for i, (desc, qty, price) in enumerate(lines, 1):
        rows.append(
            (
                f"{i} | {desc} | {_qty(qty)} | {price:,.2f} | {(qty * price).quantize(CENT):,.2f}",
                9,
                False,
            )
        )
    rows += [
        ("", 6, False),
        (f"Subtotal: {po.currency} {subtotal:,.2f}", 10, False),
        (f"Tax: {po.currency} 0.00", 10, False),
        (f"Total due: {po.currency} {subtotal:,.2f}", 12, True),
        ("", 6, False),
        (f"Please quote {number} and {po.reference} with your payment.", 9, False),
    ]
    return f"{number}.pdf", pdf.render(rows), note
