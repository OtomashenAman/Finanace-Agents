"""The Phase 3 agents' logic. Each is deterministic except reading a document (capture).

- capture (3.1): reads an invoice document; from its text every figure must appear in it,
  from an image the reading is marked for a person to confirm
- duplicate guard (3.2.2): fuzzy match on vendor, number, amount and date; blocks and
  explains
- match (3.4): line by line against the PO and what was received, with GIA tolerances
- exception (3.5.1): the case (PO, receipt, invoice side by side) and the vendor query
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field

from src.app.common import documents
from src.app.core.config import get_settings
from src.app.core.llm.base import LLMProvider
from src.app.finance_pod.invoices.models import FpInvoice
from src.app.finance_pod.orders.models import FpPurchaseOrder
from src.app.finance_pod.reference.models import FpVendor
from src.app.finance_pod.settings.models import FinancePodSettings
from src.app.service_pod.common import ai

CENT = Decimal("0.01")
CAPTURE_PROMPT_VERSION = "fpod_invoice/v1"
DUPLICATE_DAYS = 7

# --- capture (3.1) --------------------------------------------------------------------------

CAPTURE_SYSTEM = """\
You read a supplier invoice and report exactly what it states; null for anything absent.
- Numbers as printed, digits and decimal point only (no currency signs or separators).
- Dates as YYYY-MM-DD.
- `po_number`: the customer's purchase order number quoted on the invoice (e.g. PO-00012).
- `lines`: every billed line in order, with its quantity and unit price; `amount` is the
  line total as printed.
- `total`: the amount due including tax; `tax_total`: the tax amount (0 if none shown).
"""


class InvoiceLineRead(BaseModel):
    description: str
    quantity: str
    unit_price: str
    amount: str | None


class InvoiceRead(BaseModel):
    vendor_name: str | None
    vendor_tax_id: str | None
    invoice_number: str | None
    invoice_date: str | None
    due_date: str | None
    po_number: str | None
    currency: str | None = Field(description="ISO code, e.g. USD")
    tax_total: str | None
    total: str | None
    lines: list[InvoiceLineRead]


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    found = set()
    for raw in _NUMBER.findall(text):
        try:
            found.add(Decimal(raw.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return found


def number(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def capture(llm: LLMProvider, data: bytes, filename: str) -> dict[str, Any]:
    """The capture agent's reading. Raises AiOutputRejectedError when a figure it read isn't
    in the document's text (or the document can't be read)."""
    doc = documents.prepare(data, filename)
    if not doc.readable:
        raise ai.AiOutputRejectedError(f"The invoice can't be read ({doc.problem}).")
    stated = _numbers(doc.text) if doc.text else set()

    def problems(r: InvoiceRead) -> list[str]:
        if not doc.text:
            return []
        out = []
        figures = [("total", r.total), ("tax", r.tax_total)]
        for n, ln in enumerate(r.lines, start=1):
            figures += [(f"line {n} quantity", ln.quantity), (f"line {n} price", ln.unit_price)]
        for label, value in figures:
            v = number(value)
            if v is not None and v != 0 and v.normalize() not in stated:
                out.append(f"{label} {value} isn't in the invoice's text")
        return out

    result = await ai.extract(
        llm,
        system=CAPTURE_SYSTEM,
        user=f"The invoice:\n\n{doc.text}" if doc.text else "The invoice is in the images.",
        schema=InvoiceRead,
        prompt_version=CAPTURE_PROMPT_VERSION,
        validate=problems,
        images=doc.images,
    )
    return {
        **result.output.model_dump(),
        "verified": bool(doc.text),
        "provenance": result.provenance.as_dict(),
    }


def _norm_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", name.lower()).split())


def find_vendor(vendors: list[FpVendor], name: str | None, tax_id: str | None) -> FpVendor | None:
    """The vendor master entry: by tax ID, else a close name."""
    digits = documents.digits(tax_id)
    if digits:
        for v in vendors:
            if documents.digits(v.tax_id) == digits:
                return v
    if name:
        scored = [
            (SequenceMatcher(None, _norm_name(name), _norm_name(v.name)).ratio(), v)
            for v in vendors
        ]
        best = max(scored, key=lambda s: s[0], default=(0.0, None))
        if best[1] is not None and best[0] >= 0.85:
            return best[1]
    return None


def po_number_key(value: str | None) -> int | None:
    """PO-00012 / PO12 / 00012 -> 12."""
    digits = re.findall(r"\d+", value or "")
    return int(digits[-1]) if digits else None


# --- duplicate guard (3.2.2) ----------------------------------------------------------------


def _norm_number(value: str | None) -> str:
    text = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", text)


@dataclass(frozen=True)
class DuplicateHit:
    invoice_id: str
    reference: str
    vendor_invoice_number: str | None
    total: str | None
    invoice_date: str | None
    status: str
    reason: str
    strength: str  # "exact" / "likely" / "possible"


def duplicates(invoice: FpInvoice, others: list[FpInvoice]) -> list[DuplicateHit]:
    """Earlier invoices this one may repeat: same vendor and number (exact), a near-identical
    number with the same amount (likely), or the same amount within a week (possible)."""
    hits = []
    mine = _norm_number(invoice.vendor_invoice_number)
    for o in others:
        if o.id == invoice.id or o.vendor_code != invoice.vendor_code:
            continue
        theirs = _norm_number(o.vendor_invoice_number)
        same_amount = invoice.total is not None and o.total == invoice.total
        reason, strength = None, ""
        if mine and theirs and mine == theirs:
            reason = f"same vendor and invoice number ({o.vendor_invoice_number})"
            strength = "exact"
        elif mine and theirs and same_amount and SequenceMatcher(None, mine, theirs).ratio() >= 0.8:
            reason = (
                f"invoice number {o.vendor_invoice_number} is nearly the same and the "
                f"amount is identical ({o.total})"
            )
            strength = "likely"
        elif (
            same_amount
            and invoice.invoice_date
            and o.invoice_date
            and abs((invoice.invoice_date - o.invoice_date).days) <= DUPLICATE_DAYS
        ):
            reason = (
                f"same amount ({o.total}) within {DUPLICATE_DAYS} days "
                f"({o.invoice_date.isoformat()})"
            )
            strength = "possible"
        if reason:
            hits.append(
                DuplicateHit(
                    invoice_id=str(o.id),
                    reference=o.reference,
                    vendor_invoice_number=o.vendor_invoice_number,
                    total=str(o.total) if o.total is not None else None,
                    invoice_date=o.invoice_date.isoformat() if o.invoice_date else None,
                    status=o.status.value,
                    reason=reason,
                    strength=strength,
                )
            )
    order = {"exact": 0, "likely": 1, "possible": 2}
    return sorted(hits, key=lambda h: order[h.strength])


# --- match (3.4) ---------------------------------------------------------------------------------


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_name(a), _norm_name(b)).ratio()


def match(
    invoice: FpInvoice,
    po: FpPurchaseOrder | None,
    received: dict[int, Decimal],
    invoiced_elsewhere: dict[int, Decimal],
    settings: FinancePodSettings,
    credit: Decimal = Decimal("0"),
) -> dict[str, Any]:
    """Line by line against the PO and the receipts. `received`: quantity received per PO
    line; `invoiced_elsewhere`: quantity other live invoices already bill per PO line."""
    issues: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    def issue(
        kind: str, message: str, line: int | None = None, amount: Decimal | None = None
    ) -> None:
        issues.append(
            {
                "kind": kind,
                "line": line,
                "message": message,
                "amount": str(amount) if amount is not None else None,
            }
        )

    if po is None:
        issue("no_po", "The invoice quotes no purchase order of ours, or one that doesn't exist.")
        return {
            "outcome": "variance",
            "issues": issues,
            "lines": [],
            "credit": str(credit),
            "tolerances": _tolerances(settings),
        }
    if invoice.vendor_code != po.vendor_code:
        issue("vendor", f"The invoice's vendor isn't {po.reference}'s vendor ({po.vendor_name}).")
    po_lines = {ln.position: ln for ln in po.lines}
    pct = settings.price_tolerance_pct / 100
    qty_pct = settings.qty_tolerance_pct / 100
    price_variance = Decimal("0")
    for ln in invoice.lines:
        target = po_lines.get(ln.po_line or -1)
        if target is None:  # not stated: the PO line with the closest description
            scored = sorted(
                ((_similar(ln.description, p.description), p) for p in po.lines),
                key=lambda s: -s[0],
            )
            target = scored[0][1] if scored and scored[0][0] >= 0.5 else None
        row: dict[str, Any] = {
            "line": ln.position,
            "description": ln.description,
            "quantity": str(ln.quantity),
            "unit_price": str(ln.unit_price),
            "po_line": target.position if target else None,
        }
        if target is None:
            issue(
                "not_on_po",
                f"Line {ln.position} ({ln.description}) isn't on {po.reference}.",
                ln.position,
                ln.amount,
            )
            row["status"] = "not_on_po"
            lines.append(row)
            continue
        got = received.get(target.position, Decimal("0"))
        already = invoiced_elsewhere.get(target.position, Decimal("0"))
        available = got - already
        tolerance = max((target.unit_price * pct).quantize(CENT), settings.price_tolerance_amount)
        over_price = ln.unit_price - target.unit_price
        row.update(
            {
                "po_unit_price": str(target.unit_price),
                "po_quantity": str(target.quantity),
                "received": str(got),
                "invoiced_elsewhere": str(already),
                "price_tolerance": str(tolerance),
            }
        )
        status = "match"
        if over_price > tolerance:
            amount = (over_price * ln.quantity).quantize(CENT)
            price_variance += amount
            issue(
                "price",
                f"Line {ln.position}: {ln.unit_price} vs the PO's {target.unit_price} "
                f"(over by {over_price} a unit, tolerance {tolerance}): {amount} in all.",
                ln.position,
                amount,
            )
            status = "price_variance"
        if got <= 0:
            issue(
                "no_receipt",
                f"Line {ln.position}: nothing received yet on PO line {target.position}.",
                ln.position,
            )
            status = "no_receipt"
        elif ln.quantity > available * (1 + qty_pct):
            excess = ln.quantity - available
            issue(
                "quantity",
                f"Line {ln.position}: invoices {ln.quantity}, but only {available} "
                f"received and not yet invoiced (received {got}).",
                ln.position,
                (excess * ln.unit_price).quantize(CENT),
            )
            status = "quantity_variance" if status == "match" else status
        # Never more than the PO ordered (whatever was received)
        ordered_left = target.quantity - already
        if ln.quantity > ordered_left * (1 + qty_pct):
            excess = ln.quantity - ordered_left
            issue(
                "quantity",
                f"Line {ln.position}: invoices {ln.quantity}, but {po.reference} line "
                f"{target.position} has only {ordered_left} left to bill (ordered "
                f"{target.quantity}, billed elsewhere {already}).",
                ln.position,
                (excess * ln.unit_price).quantize(CENT),
            )
            status = "quantity_variance" if status == "match" else status
        row["ordered_left"] = str(ordered_left)
        row["status"] = status
        lines.append(row)

    expected_total = (invoice.lines_total + invoice.tax_total).quantize(CENT)
    if invoice.total is not None and abs(expected_total - invoice.total) > CENT:
        issue(
            "header",
            f"The lines and tax add up to {expected_total}, the invoice total is {invoice.total}.",
        )
    # A credit note received for the price variance settles it
    if credit > 0 and price_variance > 0 and credit >= price_variance:
        issues = [i for i in issues if i["kind"] != "price"]
    return {
        "outcome": "matched" if not issues else "variance",
        "issues": issues,
        "lines": lines,
        "price_variance": str(price_variance),
        "credit": str(credit),
        "tolerances": _tolerances(settings),
    }


# --- the match agent explains (3.4.2) -------------------------------------------------------

EXPLAIN_PROMPT_VERSION = "fpod_match_explain/v1"
EXPLAIN_SYSTEM = """\
You are the match agent of an accounts payable team. Explain to an AP clerk, in plain words,
how this supplier invoice compares with the purchase order and what was received: what was
ordered, what arrived, what earlier invoices already billed, what this invoice bills, what
is left to bill, whether the price matches, and so whether it can be paid or what is wrong.
Write 2 to 6 short sentences in that order. Cite the facts each sentence relies on; the
figures are shown from the facts you cite, so write no digits at all (refer to an item as
"the tubes" or "line one's item", never by a name containing digits).
"""


def quantity_trail(match_result: dict[str, Any]) -> list[dict[str, str | int | None]]:
    """Per invoice line: ordered -> received -> billed before -> this invoice -> left."""
    trail = []
    for ln in match_result.get("lines", []):
        if ln.get("po_line") is None or "po_quantity" not in ln:
            continue
        ordered = Decimal(ln["po_quantity"])
        before = Decimal(ln.get("invoiced_elsewhere") or "0")
        this = Decimal(ln["quantity"])
        trail.append(
            {
                "line": ln["line"],
                "po_line": ln["po_line"],
                "description": ln["description"],
                "ordered": _qty(ordered),
                "received": _qty(Decimal(ln.get("received") or "0")),
                "billed_before": _qty(before),
                "this_invoice": _qty(this),
                "left_to_bill": _qty(ordered - before - this),
                "po_unit_price": ln.get("po_unit_price"),
                "unit_price": ln["unit_price"],
            }
        )
    return trail


def _qty(value: Decimal) -> str:
    return f"{value.normalize():f}"


def match_facts(
    invoice: FpInvoice, po: FpPurchaseOrder | None, match_result: dict[str, Any]
) -> list[ai.Fact]:
    """The figures the explanation may cite: computed here, never by the model."""
    facts = [
        ai.Fact(
            "outcome",
            "Match outcome",
            "matched: ready for coding"
            if match_result["outcome"] == "matched"
            else "variance: exception opened",
        ),
        ai.Fact(
            "invoice.total",
            f"{invoice.vendor_invoice_number or invoice.reference} total",
            f"{invoice.total} {invoice.currency}",
        ),
        ai.Fact("po", "Purchase order", po.reference if po else "none found"),
    ]
    for t in quantity_trail(match_result):
        n = t["line"]
        facts += [
            ai.Fact(f"l{n}.item", f"Line {n} item", str(t["description"])),
            ai.Fact(f"l{n}.ordered", f"Line {n} ordered on the PO", str(t["ordered"])),
            ai.Fact(f"l{n}.received", f"Line {n} received so far", str(t["received"])),
            ai.Fact(
                f"l{n}.billed_before",
                f"Line {n} billed by earlier invoices",
                str(t["billed_before"]),
            ),
            ai.Fact(f"l{n}.this", f"Line {n} billed by this invoice", str(t["this_invoice"])),
            ai.Fact(
                f"l{n}.left", f"Line {n} left to bill after this invoice", str(t["left_to_bill"])
            ),
            ai.Fact(
                f"l{n}.price",
                f"Line {n} unit price (invoice / PO)",
                f"{t['unit_price']} / {t['po_unit_price']}",
            ),
        ]
    tol = match_result.get("tolerances", {})
    facts.append(
        ai.Fact(
            "tolerance",
            "Price tolerance",
            f"{tol.get('price_pct')}% or {tol.get('price_amount')} a unit",
        )
    )
    for k, issue in enumerate(match_result.get("issues", []), start=1):
        facts.append(ai.Fact(f"issue{k}", f"Issue {k}", issue["message"]))
    return facts


async def explain(
    llm: LLMProvider, invoice: FpInvoice, po: FpPurchaseOrder | None, match_result: dict[str, Any]
) -> dict[str, Any]:
    facts = match_facts(invoice, po, match_result)
    ask = "Explain this invoice's three-way match."
    try:
        result = await ai.cited_narrative(
            llm, system=EXPLAIN_SYSTEM, facts=facts, ask=ask, prompt_version=EXPLAIN_PROMPT_VERSION
        )
    except ai.AiOutputRejectedError as exc:
        # One retry, told what was refused (usually a figure or an item name with digits)
        result = await ai.cited_narrative(
            llm,
            system=EXPLAIN_SYSTEM,
            facts=facts,
            ask=f"{ask} Your previous answer was refused ({exc.message.split(': ', 1)[-1]}). "
            "Rewrite it with no digits anywhere: cite the facts instead.",
            prompt_version=EXPLAIN_PROMPT_VERSION,
        )
    return {
        "highlights": [h.model_dump() for h in result.output.highlights],
        "facts": [{"id": f.id, "label": f.label, "value": f.value} for f in facts],
        "provenance": result.provenance.as_dict(),
    }


def _tolerances(settings: FinancePodSettings) -> dict[str, str]:
    return {
        "price_pct": str(settings.price_tolerance_pct),
        "price_amount": str(settings.price_tolerance_amount),
        "qty_pct": str(settings.qty_tolerance_pct),
    }


# --- exception (3.5.1) ------------------------------------------------------------------------


def vendor_query(
    invoice: FpInvoice,
    po: FpPurchaseOrder | None,
    issues: list[dict[str, Any]],
    credit: Decimal | None = None,
) -> tuple[str, str]:
    """The exception agent's draft to the vendor: the facts, nothing invented."""
    org = get_settings().email_sender_name
    facts = "\n".join(
        f"  - {i['message']}"
        for i in issues
        if i["kind"] in ("price", "quantity", "not_on_po", "header", "vendor")
    )
    ask = (
        f"Please send a credit note for {credit:,.2f} {invoice.currency}, quoting your invoice "
        f"{invoice.vendor_invoice_number}."
        if credit
        else "Please confirm the correct figures or send a corrected invoice."
    )
    body = (
        f"Hello {invoice.vendor_name or 'there'},\n\n"
        f"We can't pay your invoice {invoice.vendor_invoice_number or ''}"
        f"{f' against our {po.reference}' if po else ''} as it stands:\n\n"
        f"{facts or '  - see above'}\n\n"
        f"{ask}\n\nThank you,\n{org}"
    )
    return f"Your invoice {invoice.vendor_invoice_number or ''}: query from {org}", body


def due_date_default(invoice_date: date | None, terms: str | None) -> date | None:
    """Net N payment terms from the invoice date."""
    m = re.search(r"net\s*(\d+)", terms or "", re.IGNORECASE)
    if invoice_date and m:
        return invoice_date + timedelta(days=int(m.group(1)))
    return None
