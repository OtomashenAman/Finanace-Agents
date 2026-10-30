"""Reporting periods as people write them: a month (2026-09), a quarter (2026-Q3) or a year
(2026). Used to add up monthly figures from a data source."""

import re
from datetime import date

from src.app.data_sources.records import month_end

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)
_YEAR = re.compile(r"^(\d{4})$")


def months_of(period: str) -> list[str] | None:
    """The months a period covers, oldest first; None if it isn't a month, quarter or year."""
    text = period.strip()
    if match := _MONTH.match(text):
        return [text]
    if match := _QUARTER.match(text):
        year, quarter = int(match[1]), int(match[2])
        return [f"{year:04d}-{m:02d}" for m in range(quarter * 3 - 2, quarter * 3 + 1)]
    if match := _YEAR.match(text):
        return [f"{int(match[1]):04d}-{m:02d}" for m in range(1, 13)]
    return None


def same_period_last_year(period: str) -> str | None:
    """2026-Q3 -> 2025-Q3 (also months and years); None if the period isn't recognised."""
    text = period.strip()
    if months_of(text) is None:
        return None
    return f"{int(text[:4]) - 1:04d}{text[4:].upper()}"


def period_end(period: str) -> date | None:
    """The last day of a month, quarter or year."""
    months = months_of(period)
    return month_end(months[-1]) if months else None


def period_options(months: set[str]) -> list[str]:
    """Periods fully covered by `months`: each month, then complete quarters and years,
    newest first within each."""
    quarters = {f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}" for m in months}
    complete_quarters = [q for q in quarters if set(months_of(q) or []) <= months]
    complete_years = [y for y in {m[:4] for m in months} if set(months_of(y) or []) <= months]
    return [
        *sorted(months, reverse=True),
        *sorted(complete_quarters, reverse=True),
        *sorted(complete_years, reverse=True),
    ]
