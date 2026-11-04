"""The sourcing agent (Phase 1.3.1).

a. finds approved vendors for the request: those with contract prices for its lines (the
   request agent's catalogue matching) and those whose categories cover its lines
b. drafts the quote requests sent above the purchasing threshold (a person sends them)
c. reads a quote document (AI; every figure must be in the document's text) and compares
   the options side by side (computed: lowest price, fastest, contract vendor, expiry)
"""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

from src.app.core.config import get_settings
from src.app.core.llm.base import LLMProvider
from src.app.finance_pod import documents
from src.app.finance_pod.reference.models import VendorStatus
from src.app.finance_pod.requests.agent import Reference, price_checks
from src.app.finance_pod.requests.models import FpPurchaseRequest
from src.app.finance_pod.sourcing.models import FpQuote, QuoteStatus
from src.app.finance_pod.sourcing.schemas import Candidate, ComparisonRow
from src.app.service_pod.common import ai

QUOTE_PROMPT_VERSION = "fpod_quote/v1"


def candidates(request: FpPurchaseRequest, ref: Reference, today: date) -> list[Candidate]:
    checks = price_checks(request, ref, today)
    by_vendor: dict[str, list[int]] = {}
    contract_total: dict[str, Decimal] = {}
    for c in checks:
        if c.vendor_code and c.contract_price is not None:
            by_vendor.setdefault(c.vendor_code, []).append(c.line)
            line = request.lines[c.line - 1]
            contract_total[c.vendor_code] = contract_total.get(c.vendor_code, Decimal("0")) + (
                c.contract_price * line.quantity
            ).quantize(Decimal("0.01"))
    categories = {ln.category for ln in request.lines if ln.category}
    found = []
    for vendor in ref.vendors.values():
        if vendor.status != VendorStatus.APPROVED or not vendor.active:
            continue
        lines = by_vendor.get(vendor.code, [])
        shared = sorted(categories & set(vendor.categories))
        if not lines and not shared:
            continue
        reasons = []
        if lines:
            reasons.append(
                f"contract prices for line{'s' if len(lines) > 1 else ''} "
                f"{', '.join(map(str, lines))}"
            )
        if shared:
            reasons.append(f"approved for {', '.join(shared)}")
        found.append(
            Candidate(
                vendor_code=vendor.code,
                vendor_name=vendor.name,
                vendor_email=vendor.email,
                reasons=reasons,
                contract_lines=lines,
                contract_total=contract_total.get(vendor.code),
                covers_all_lines=bool(request.lines) and len(lines) == len(request.lines),
            )
        )
    # Contract coverage first, then category matches; then by name
    found.sort(key=lambda c: (-len(c.contract_lines), c.vendor_name.lower()))
    return found


def quote_request_email(
    request: FpPurchaseRequest, vendor_name: str, reply_by: date, message: str
) -> tuple[str, str]:
    """(subject, body). No budget or estimate figures: vendors quote their own price."""
    lines = "\n".join(
        f"  {n}. {ln.description}: {ln.quantity.normalize():f} {ln.unit or ''}".rstrip()
        for n, ln in enumerate(request.lines, start=1)
    )
    needed = request.needed_by.strftime("%d %B %Y") if request.needed_by else "as soon as possible"
    body = (
        f"Hello {vendor_name},\n\n"
        f"We would like a quotation for the following ({request.reference}):\n\n{lines}\n\n"
        f"Needed by: {needed}\n"
        + (f"\n{message.strip()}\n" if message.strip() else "")
        + f"\nPlease reply by {reply_by.strftime('%d %B %Y')} with your total price, the "
        "currency, the lead time, your payment terms and how long the quote is valid, "
        f"quoting {request.reference}. A PDF quotation is welcome.\n\n"
        f"Thank you,\n{get_settings().email_sender_name}"
    )
    return f"Request for quotation {request.reference}: {request.title}", body


# --- c. reading a quote ----------------------------------------------------------------

QUOTE_SYSTEM = """\
You read a vendor's quotation and report what it states. Use only what the document says.
- `total`: the grand total to pay, as written (digits and decimal point only), or null.
- `currency`: ISO code (USD, EUR...) if stated, else null.
- `lead_time_days`: delivery lead time in days if stated (convert weeks x 7), else null.
- `payment_terms`: e.g. "Net 30", as written, else null.
- `valid_until`: YYYY-MM-DD if the quote states a validity date, else null.
- `quote_reference`: the vendor's quote number, else null.
"""


class QuoteRead(BaseModel):
    vendor_name: str | None = Field(description="The quoting company's name as written")
    total: str | None
    currency: str | None
    lead_time_days: int | None
    payment_terms: str | None
    valid_until: str | None
    quote_reference: str | None


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    out = set()
    for raw in _NUMBER.findall(text):
        try:
            out.add(Decimal(raw.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return out


async def read_quote(llm: LLMProvider, data: bytes, filename: str) -> dict[str, object]:
    """What the agent read, checked: from text, the total must appear in it; from an image
    it can't be checked, so `verified` is False and a person confirms it."""
    doc = documents.prepare(data, filename)
    if not doc.readable:
        raise ai.AiOutputRejectedError(f"The quote can't be read ({doc.problem}).")
    stated = _numbers(doc.text) if doc.text else set()

    def problems(r: QuoteRead) -> list[str]:
        if doc.text and r.total is not None:
            try:
                total = Decimal(r.total.replace(",", "")).normalize()
            except InvalidOperation:
                return ["the total isn't a number"]
            if total not in stated:
                return [f"the total {r.total} isn't in the quote's text"]
        return []

    result = await ai.extract(
        llm,
        system=QUOTE_SYSTEM,
        user=f"The quotation:\n\n{doc.text}" if doc.text else "The quotation is in the images.",
        schema=QuoteRead,
        prompt_version=QUOTE_PROMPT_VERSION,
        validate=problems,
        images=doc.images,
    )
    return {
        **result.output.model_dump(),
        "verified": bool(doc.text),
        "provenance": result.provenance.as_dict(),
    }


def parse_total(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return d if d >= 0 else None


def parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def comparison(
    request: FpPurchaseRequest,
    quotes: list[FpQuote],
    cands: list[Candidate],
    known_vendors: set[str],
    today: date,
) -> list[ComparisonRow]:
    estimate = request.total
    rows: list[ComparisonRow] = []
    contract_vendors = {c.vendor_code for c in cands if c.contract_lines}
    for q in quotes:
        if q.status != QuoteStatus.RECEIVED or q.total is None:
            continue
        arrives = today + timedelta(days=q.lead_time_days) if q.lead_time_days is not None else None
        rows.append(
            ComparisonRow(
                option="quote",
                quote_id=q.id,
                vendor_code=q.vendor_code,
                vendor_name=q.vendor_name,
                total=q.total,
                vs_estimate=q.total - estimate,
                lead_time_days=q.lead_time_days,
                arrives_by=arrives,
                meets_needed_by=(
                    arrives <= request.needed_by if arrives and request.needed_by else None
                ),
                payment_terms=q.payment_terms,
                valid_until=q.valid_until,
                expired=bool(q.valid_until and q.valid_until < today),
                new_vendor=not q.vendor_code or q.vendor_code not in known_vendors,
                flags=["contract vendor"] if q.vendor_code in contract_vendors else [],
            )
        )
    for c in cands:
        if c.covers_all_lines and c.contract_total is not None:
            rows.append(
                ComparisonRow(
                    option="contract",
                    quote_id=None,
                    vendor_code=c.vendor_code,
                    vendor_name=c.vendor_name,
                    total=c.contract_total,
                    vs_estimate=c.contract_total - estimate,
                    lead_time_days=None,
                    arrives_by=None,
                    meets_needed_by=None,
                    payment_terms=None,
                    valid_until=None,
                    expired=False,
                    new_vendor=False,
                    flags=["contract prices"],
                )
            )
    live = [r for r in rows if not r.expired]
    if live:
        lowest = min(r.total for r in live)
        for r in live:
            if r.total == lowest:
                r.flags.insert(0, "lowest price")
        timed = [r for r in live if r.lead_time_days is not None]
        if timed:
            fastest = min(r.lead_time_days or 0 for r in timed)
            for r in timed:
                if r.lead_time_days == fastest:
                    r.flags.append("fastest")
    for r in rows:
        if r.expired:
            r.flags.append("expired")
        if r.new_vendor:
            r.flags.append("new vendor: onboarding needed")
    rows.sort(key=lambda r: (r.expired, r.total))
    return rows
