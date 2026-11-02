"""The management pack's figures and controls (TDD section 10), from the source alone.

The report month is compared with the calendar month before through the FP&A trend engine
(drivers reconciled to the GL: an unexplained movement blocks). Each month needs exactly one
Balance Sheet, and assets = liabilities + equity within half a cent. The report month must
be Closed. AR aging keeps the snapshot's own as-of date: current balances are never labelled
month-end balances; when the dates differ the case raises a scope task.
"""

from decimal import Decimal
from typing import Any

from src.app.data_sources.records import month_end
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.flows.fpa_trend import engine as trend
from src.app.service_pod.flows.fpa_trend.schemas import FpaSelection
from src.app.service_pod.flows.reporting.schemas import ReportingSelection

TOLERANCE = Decimal("0.005")  # half a cent
BUCKETS = (
    ("Current", None, 0),
    ("1-30", 1, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("90+", 91, None),
)


def prior_month(month: str) -> str:
    year, m = int(month[:4]), int(month[5:])
    year, m = (year, m - 1) if m > 1 else (year - 1, 12)
    return f"{year:04d}-{m:02d}"


def _control(key: str, label: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "status": "pass" if ok else "fail", "detail": detail}


def compute(doc: SnapshotDocument, sel: ReportingSelection) -> dict[str, Any]:
    if doc.balance_sheets is None or doc.close_status is None or doc.invoices is None:
        raise CaseSelectionError(
            "Reporting needs the source's Balance Sheets, close status and invoices."
        )
    prior = prior_month(sel.month)
    pack = trend.compute(
        doc, FpaSelection(start=prior, end=sel.month, business_unit=sel.business_unit)
    )
    issues: list[dict[str, Any]] = pack["issues"]
    controls = []

    sheets: dict[str, Any] = {}
    for period in (prior, sel.month):
        found = [b for b in doc.balance_sheets if b.period == period]
        if len(found) != 1:
            issues.append(
                {
                    "code": "balance_sheet_count",
                    "detail": f"{period}: the source has {len(found)} Balance Sheets; exactly one "
                    "is needed. Import a source with the month's Balance Sheet.",
                    "blocking": True,
                }
            )
            sheets[period] = None
            continue
        b = found[0]
        difference = b.assets - (b.liabilities + b.equity)
        balanced = abs(difference) <= TOLERANCE
        if not balanced:
            issues.append(
                {
                    "code": "balance_sheet_unbalanced",
                    "detail": f"{period}: assets {b.assets} don't equal liabilities "
                    f"{b.liabilities} + equity {b.equity} (difference {difference}). Correct "
                    "the source.",
                    "blocking": True,
                }
            )
        sheets[period] = {
            "assets": b.assets,
            "liabilities": b.liabilities,
            "equity": b.equity,
            "difference": difference,
            "balanced": balanced,
            "report_id": b.report_id,
        }
    controls.append(
        _control(
            "balance_sheets",
            "Balance Sheets",
            all(s is not None for s in sheets.values()),
            "Exactly one Balance Sheet for each month",
        )
    )
    controls.append(
        _control(
            "balanced",
            "Assets = liabilities + equity",
            all(s is not None and s["balanced"] for s in sheets.values()),
            "Within half a cent",
        )
    )

    close = next((c for c in doc.close_status if c.period == sel.month), None)
    closed = close is not None and close.status == "Closed"
    if not closed:
        issues.append(
            {
                "code": "period_open",
                "detail": f"{sel.month} isn't Closed in the source"
                + (" (no close status for it)" if close is None else "")
                + ": a management pack is only for a closed month.",
                "blocking": True,
            }
        )
    controls.append(
        _control(
            "closed",
            "Period closed",
            closed,
            f"{sel.month} is {close.status if close else 'not in the close status'}",
        )
    )
    controls.append(
        _control(
            "reconciled",
            "Transactions explain the GL",
            not any(i["code"] == "unexplained_delta" for i in issues),
            "Every account's movement equals its Posted transactions",
        )
    )

    open_items = [i for i in doc.invoices if i.balance > 0]
    aging: list[dict[str, Any]] = []
    total = Decimal(0)
    for label, low, high in BUCKETS:
        rows = [
            i
            for i in open_items
            if (low is None and i.due_date >= doc.as_of)
            or (
                low is not None
                and (doc.as_of - i.due_date).days >= low
                and (high is None or (doc.as_of - i.due_date).days <= high)
            )
        ]
        amount = sum((i.balance for i in rows), Decimal(0))
        aging.append({"label": label, "amount": amount, "count": len(rows)})
        total += amount
    end = month_end(sel.month)
    return {
        **pack,
        "issues": issues,
        "report_month": sel.month,
        "prior_month": prior,
        "balance_sheets": sheets,
        "close": {
            "status": close.status if close else None,
            "required_checks": list(close.required_checks) if close else [],
        },
        "aging": {
            "as_of": doc.as_of,
            "month_end": end,
            # current balances as of the snapshot date, never relabelled as month-end
            "matches_month_end": doc.as_of == end,
            "buckets": aging,
            "total": total,
        },
        "controls": controls,
    }


def blocking(state: dict[str, Any]) -> list[str]:
    return trend.blocking_issues(state)
