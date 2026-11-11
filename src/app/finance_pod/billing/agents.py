"""The billing agent (3.1) and the fee-rule agent (3.2).

Billing agent: on the "report issued" event, builds the invoice from the services actually
performed and the client's account terms. Fee-rule agent: prices each line from the fee
schedule (or the client's contract price), applies currency and tax by client location,
then checks the result against the intake estimate and flags what is unusual. Flags and
price overrides go to the billing analyst; a clean invoice goes straight to delivery.

Both only read the fee schedule: it changes by an admin's workbook upload, never here.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod.billing.models import (
    FpContractPrice,
    FpFee,
    FpLabSubmission,
    FpSalesInvoice,
    FpSalesInvoiceLine,
    FpSubmissionLine,
    FpTaxRate,
    OverrideStatus,
    SalesInvoiceStatus,
)
from src.app.finance_pod.clients.models import ClientStatus, FpClient

CENT = Decimal("0.01")
US_STATE = re.compile(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")

Flag = dict[str, Any]  # {key, label, detail, cleared?: {by, note, at}}


def _flag(key: str, label: str, detail: str) -> Flag:
    return {"key": key, "label": label, "detail": detail}


def region_of(client: FpClient) -> str | None:
    """The client's state/region for tax: from a US address ('... Philadelphia PA 19103')."""
    if (client.country or "US") == "US" and client.address:
        found = US_STATE.findall(client.address.upper())
        return found[-1] if found else None
    return None


@dataclass
class Price:
    name: str | None  # the service's published name
    list_price: Decimal | None
    unit_price: Decimal
    source: str  # schedule / contract / none
    note: str | None
    currency: str | None
    flags: list[Flag]


def _fits(fee: FpFee, line: FpSubmissionLine) -> bool:
    if fee.stone_type and fee.stone_type != line.stone_type.lower():
        return False
    if fee.carat_from is not None or fee.carat_to is not None:
        if line.carat is None:
            return False
        if fee.carat_from is not None and line.carat < fee.carat_from:
            return False
        if fee.carat_to is not None and line.carat >= fee.carat_to:
            return False
    return True


def _best(fees: list[FpFee], line: FpSubmissionLine, turnaround: str) -> FpFee | None:
    """The most specific fee that fits: this stone type over 'any stone'."""
    fitting = [f for f in fees if f.turnaround == turnaround and _fits(f, line)]
    fitting.sort(key=lambda f: (f.stone_type is None, f.carat_from is None))
    return fitting[0] if fitting else None


async def price_line(
    session: AsyncSession, client: FpClient, line: FpSubmissionLine, turnaround: str, today: date
) -> Price:
    """The fee-rule agent's price for one line (3.2.1)."""
    fees = list(await session.scalars(select(FpFee).where(FpFee.service_code == line.service_code)))
    flags: list[Flag] = []
    fee = _best(fees, line, turnaround)
    if fee is None and turnaround != "standard":
        fee = _best(fees, line, "standard")
        if fee is not None:
            flags.append(
                _flag(
                    "turnaround",
                    "No fee for this turnaround",
                    f"No {turnaround} fee published for {line.service_code}: the standard fee "
                    "is used.",
                )
            )
    if fee is None:
        return Price(
            None,
            None,
            Decimal("0.00"),
            "none",
            None,
            None,
            [
                _flag(
                    "not_on_schedule",
                    "Not on the fee schedule",
                    f"No published fee for {line.service_code} on a {line.stone_type}"
                    + (f" of {line.carat} ct" if line.carat is not None else "")
                    + ": the analyst sets the price.",
                )
            ],
        )
    contract = await session.scalar(
        select(FpContractPrice).where(
            FpContractPrice.client_code == client.code,
            FpContractPrice.service_code == line.service_code,
        )
    )
    if contract and contract.valid_to and contract.valid_to < today:
        flags.append(
            _flag(
                "contract_expired",
                "Contract price expired",
                f"{contract.contract_ref or 'The contract'} ended {contract.valid_to}: the "
                "published fee is used.",
            )
        )
        contract = None
    if contract is not None:
        if contract.price is not None:
            unit, note = contract.price, f"contract price ({contract.contract_ref or 'contract'})"
        else:
            pct = contract.discount_pct or Decimal("0")
            unit = (fee.fee * (100 - pct) / 100).quantize(CENT)
            note = f"{pct:g}% contract discount ({contract.contract_ref or 'contract'})"
        return Price(fee.service_name, fee.fee, unit, "contract", note, fee.currency, flags)
    return Price(fee.service_name, fee.fee, fee.fee, "schedule", None, fee.currency, flags)


async def build(
    session: AsyncSession,
    submission: FpLabSubmission,
    client: FpClient,
    estimate_tolerance: Decimal,
) -> FpSalesInvoice:
    """The billing agent builds the invoice (3.1.2), the fee-rule agent prices and checks it
    (3.2). The caller adds it to the session."""
    today = utcnow().date()
    invoice = FpSalesInvoice(
        status=SalesInvoiceStatus.REVIEW,
        submission_id=submission.id,
        client_id=client.id,
        client_code=client.code,
        client_name=client.name,
        bill_to_email=client.billing_email,
        currency=client.currency,
        payment_terms=client.payment_terms,
        deposit_pct=client.deposit_pct,
        estimate=submission.estimate,
        built_at=utcnow(),
        subtotal=Decimal("0"),
        discount_total=Decimal("0"),
        tax_rate=Decimal("0"),
        tax=Decimal("0"),
        total=Decimal("0"),
    )
    currencies: set[str] = set()
    position = 0
    for sl in submission.lines:
        if not sl.performed:
            continue  # requested but not done: not billed
        position += 1
        p = await price_line(session, client, sl, submission.turnaround, today)
        if p.currency:
            currencies.add(p.currency)
        flags = list(p.flags)
        if not sl.requested:
            flags.append(
                _flag(
                    "added_service",
                    "Service added in the lab",
                    f"{sl.service_code} on {sl.item_ref} wasn't asked for at intake: confirm "
                    "the client agreed to it.",
                )
            )
        line = FpSalesInvoiceLine(
            position=position,
            item_ref=sl.item_ref,
            service_code=sl.service_code,
            description=p.name or sl.service_code,
            stone_type=sl.stone_type,
            carat=sl.carat,
            quantity=sl.quantity,
            list_price=p.list_price,
            unit_price=p.unit_price,
            price_source=p.source,
            price_note=p.note,
            amount=(p.unit_price * sl.quantity).quantize(CENT),
            flags=flags,
        )
        if sl.special_price is not None:
            line.override_price = sl.special_price
            line.override_reason = sl.special_reason or "Special price agreed at intake"
            line.override_status = OverrideStatus.PENDING
        invoice.lines.append(line)

    inv_flags: list[Flag] = []
    if client.status == ClientStatus.ON_HOLD:
        inv_flags.append(
            _flag(
                "client_on_hold",
                "Client on hold",
                f"{client.code} is on hold: collect the {client.deposit_pct:g}% deposit before "
                "releasing the reports.",
            )
        )
    if currencies - {client.currency}:
        inv_flags.append(
            _flag(
                "currency",
                "Currency differs",
                f"Fees are published in {', '.join(sorted(currencies))}; the client is billed in "
                f"{client.currency}. Check the conversion.",
            )
        )
    region = region_of(client)
    country = client.country or "US"
    rate = (
        await session.scalar(
            select(FpTaxRate).where(FpTaxRate.country == country, FpTaxRate.region == region)
        )
        if region
        else None
    )
    rate = rate or await session.scalar(
        select(FpTaxRate).where(FpTaxRate.country == country, FpTaxRate.region.is_(None))
    )
    if rate is None:
        inv_flags.append(
            _flag(
                "no_tax_rate",
                "No tax rate for the client's location",
                f"No rate for {country}{f' / {region}' if region else ''}: add it to the fee "
                "schedule, or confirm no tax applies.",
            )
        )
    else:
        invoice.tax_name, invoice.tax_rate = rate.name, rate.rate_pct
    invoice.flags = inv_flags
    totals(invoice)
    if invoice.estimate is not None and invoice.estimate > 0:
        limit = invoice.estimate * (100 + estimate_tolerance) / 100
        if invoice.subtotal > limit:
            over = (invoice.subtotal / invoice.estimate - 1) * 100
            invoice.flags = [
                *invoice.flags,
                _flag(
                    "above_estimate",
                    "Above the fee estimate",
                    f"{invoice.currency} {invoice.subtotal:,.2f} is {over:.0f}% over the intake "
                    f"estimate of {invoice.currency} {invoice.estimate:,.2f} (tolerance "
                    f"{estimate_tolerance:g}%).",
                ),
            ]
    invoice.flagged_on_build = bool(open_items(invoice))
    return invoice


def totals(invoice: FpSalesInvoice) -> None:
    """Recompute the lines' amounts and the invoice totals (after an override)."""
    subtotal = discount = Decimal("0")
    for ln in invoice.lines:
        if ln.override_status == OverrideStatus.APPROVED and ln.override_price is not None:
            ln.unit_price, ln.price_source = ln.override_price, "override"
        ln.amount = (ln.unit_price * ln.quantity).quantize(CENT)
        subtotal += ln.amount
        if ln.list_price is not None and ln.list_price > ln.unit_price:
            discount += (ln.list_price - ln.unit_price) * ln.quantity
    invoice.subtotal = subtotal.quantize(CENT)
    invoice.discount_total = discount.quantize(CENT)
    invoice.tax = (invoice.subtotal * invoice.tax_rate / 100).quantize(CENT)
    invoice.total = invoice.subtotal + invoice.tax


def open_items(invoice: FpSalesInvoice) -> list[str]:
    """What still stops the invoice going out: flags nobody cleared, overrides to decide,
    lines without a price."""
    items = [f["label"] for f in invoice.flags if not f.get("cleared")]
    for ln in invoice.lines:
        items += [f"{ln.item_ref}: {f['label']}" for f in ln.flags if not f.get("cleared")]
        if ln.override_status == OverrideStatus.PENDING:
            items.append(f"{ln.item_ref}: price override to approve")
        if ln.price_source == "none":
            items.append(f"{ln.item_ref}: no price")
    return items
