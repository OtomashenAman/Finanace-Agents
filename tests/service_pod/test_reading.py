from datetime import date
from decimal import Decimal

import pytest

from src.app.service_pod.common import reading


@pytest.mark.parametrize(
    ("text", "amounts"),
    [
        ("Pay $6k now and $9k Nov 20 for INV-101.", {6000, 9000, 20}),
        ("$4k approved and $6k disputed on INV-102", {4000, 6000}),
        ("Apply $6,000 to INV-101 and $3,000 to INV-102.", {6000, 3000}),
        ("All $9,000.00 is for INV-101", {Decimal("9000.00")}),
        ("USD 15000 on the 12th", {15000}),  # an ordinal day is not an amount
    ],
)
def test_amounts_in_customer_words(text: str, amounts: set[Decimal]) -> None:
    assert reading.amounts_in(text) == {Decimal(a) for a in amounts}


@pytest.mark.parametrize(
    ("quote", "when", "supported"),
    [
        ("Pay both on Nov 12.", date(2026, 11, 12), True),
        ("on 12 November", date(2026, 11, 12), True),
        ("by 2026-11-20", date(2026, 11, 20), True),
        ("$9k Nov 20", date(2026, 11, 12), False),
        ("Pay $6k now", date(2026, 11, 5), False),  # "now" isn't a date
    ],
)
def test_date_supported(quote: str, when: date, supported: bool) -> None:
    assert reading.date_supported(quote, when) is supported


def test_quotes_and_conditions() -> None:
    reply = "Hi,\nWe\u2019ll pay  $6k   now and $9k Nov 20 for INV-101.\nThanks"
    assert reading.quote_in(reply, "We'll pay $6k now")
    assert not reading.quote_in(reply, "We will pay $6k today")
    assert reading.conditional("We will pay once the timesheets are approved")
    assert not reading.conditional("Pay both on Nov 12.")
