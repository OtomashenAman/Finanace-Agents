"""Deterministic checks on what the AI read from a customer's email: every figure it reports
must be in the customer's own words. Nothing here guesses."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_MONTHS = {
    name: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
# 9000 / 9,000 / $9,000.00 / $6k / USD 15000 (not invoice numbers like INV-101)
_AMOUNT = re.compile(
    r"(?<![\w.\-/])(?:[$€£₹]\s?|usd\s?)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(k|m)?(?![\w\-/])",
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(
    r"\b(if|once|provided|unless|subject to|depending|assuming|upon|as soon as)\b", re.IGNORECASE
)


def normalize(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(text.lower().split())


def quote_in(source: str, quote: str) -> bool:
    """The quote is the customer's own words, copied from the email."""
    q = normalize(quote).strip(" .\"'")
    return len(q) >= 3 and q in normalize(source)


def amounts_in(text: str) -> set[Decimal]:
    found = set()
    for whole, cents, scale in _AMOUNT.findall(text):
        try:
            value = Decimal(whole.replace(",", "") + (f".{cents}" if cents else ""))
        except InvalidOperation:
            continue
        if scale:
            value *= 1000 if scale.lower() == "k" else 1_000_000
        found.add(value)
    return found


def amount_supported(quote: str, amount: Decimal) -> bool:
    return amount in amounts_in(quote)


def date_supported(quote: str, when: date) -> bool:
    """The quote names this calendar date (Nov 12, 12 November, 2026-11-12, 11/12)."""
    text = normalize(quote)
    if when.isoformat() in text:
        return True
    words = re.findall(r"[a-z]+|\d+", text)
    months = {_MONTHS[w] for w in words if w in _MONTHS}
    days = {int(w) for w in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", text)}
    if when.month in months and when.day in days:
        return True
    return f"{when.month}/{when.day}" in text or f"{when.day}/{when.month}" in text


def conditional(quote: str) -> bool:
    return _CONDITIONAL.search(quote) is not None


def parse_money(value: str) -> Decimal | None:
    try:
        amount = Decimal(value.replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None
    return amount.quantize(Decimal("0.01")) if amount.is_finite() and amount > 0 else None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def money(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def dec(value: Any) -> Decimal:
    """A stored amount (case state keeps them as strings) back as a Decimal."""
    return Decimal(str(value))
