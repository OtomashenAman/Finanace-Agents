"""The FP&A trend pack, computed from the source alone (TDD section 8). No AI here.

For each month: revenue = Income, cost of services = CostOfGoodsSold, operating expense =
Expense (as the P&L / GL lines state them); gross profit, total operating cost, operating
profit and margin follow. Month-on-month drivers come from Posted transactions only and are
reconciled with the GL account deltas: a difference the transactions don't explain blocks
approval. OtherIncome / OtherExpense stay outside the operating figures and are disclosed.
Nothing missing is filled in: a skipped month refuses the case, an absent category is a
blocking issue (a true zero needs an explicit zero row).
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from typing import Any

from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.snapshots.contract import (
    AccountClass,
    GlLine,
    SnapshotDocument,
    Transaction,
)
from src.app.service_pod.flows.fpa_trend.schemas import FpaSelection

OPERATING = {
    AccountClass.INCOME: "revenue",
    AccountClass.COST_OF_GOODS_SOLD: "cost_of_services",
    AccountClass.EXPENSE: "operating_expense",
}
NON_OPERATING = {
    AccountClass.OTHER_INCOME: "other_income",
    AccountClass.OTHER_EXPENSE: "other_expense",
}
OUTLIER_PCT = Decimal(10)  # |revenue MoM| at least this: the descriptive outlier flag
SEASONAL_MIN_MONTHS = 24
TOP_CONTRIBUTORS = 8
ZERO = Decimal(0)
CENT = Decimal("0.01")
PCT = Decimal("0.0001")


def months_between(start: str, end: str) -> list[str]:
    """Every calendar month from start to end, inclusive (YYYY-MM)."""
    year, month = int(start[:4]), int(start[5:])
    out = []
    while f"{year:04d}-{month:02d}" <= end:
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return out


def prior_year(period: str) -> str:
    return f"{int(period[:4]) - 1:04d}{period[4:]}"


def pct_change(current: Decimal, prior: Decimal) -> Decimal | None:
    """100 * (current - prior) / prior; a zero baseline is undefined (None), never /0."""
    if prior == 0:
        return None
    return (100 * (current - prior) / abs(prior)).quantize(PCT, ROUND_HALF_UP)


def margin(profit: Decimal, revenue: Decimal) -> Decimal | None:
    """100 * operating profit / revenue; zero revenue is undefined (None)."""
    if revenue == 0:
        return None
    return 100 * profit / revenue


def _q(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(PCT, ROUND_HALF_UP)


@dataclass
class Issue:
    code: str
    detail: str
    blocking: bool

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "blocking": self.blocking}


def _in_unit(row: GlLine | Transaction, unit: str | None) -> bool:
    return unit is None or row.business_unit == unit


def available_months(doc: SnapshotDocument) -> list[str]:
    return sorted({g.period for g in doc.gl_lines or []})


def suggested_range(months: list[str]) -> tuple[str, str] | None:
    """The latest run of consecutive months, at most six (TDD: six when present)."""
    if len(months) < 2:
        return None
    run = [months[-1]]
    for m in reversed(months[:-1]):
        if months_between(m, run[0])[1:] != [run[0]] or len(run) == 6:
            break
        run.insert(0, m)
    return (run[0], run[-1]) if len(run) >= 2 else None


def compute(doc: SnapshotDocument, sel: FpaSelection) -> dict[str, Any]:
    """The whole trend pack for the selected months (raise CaseSelectionError to refuse)."""
    if doc.accounts is None or doc.gl_lines is None or doc.transactions is None:
        raise CaseSelectionError("FP&A needs the source's accounts, GL lines and transactions.")
    months = months_between(sel.start, sel.end)
    unit = sel.business_unit
    accounts = {a.id: a for a in doc.accounts}
    lines = [g for g in doc.gl_lines if _in_unit(g, unit)]
    present = {g.period for g in lines}
    missing = [m for m in months if m not in present]
    if missing:
        raise CaseSelectionError(
            f"The source has no P&L lines for {', '.join(missing)}"
            + (f" ({unit})" if unit else "")
            + ": missing months are never filled in. Choose consecutive months the source covers."
        )

    issues: list[Issue] = []
    caveats: list[str] = []
    # Per month and class: the GL amounts (None = the category has no row at all)
    by_month: dict[str, dict[str, Decimal | None]] = {}
    gl_by_account: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for m in months:
        totals: dict[str, Decimal | None] = dict.fromkeys(
            [*OPERATING.values(), *NON_OPERATING.values()], None
        )
        for g in lines:
            if g.period != m:
                continue
            cls = accounts[g.account_id].classification
            key = OPERATING.get(cls) or NON_OPERATING.get(cls)
            if key is None:
                continue  # balance sheet accounts don't belong in the P&L trend
            totals[key] = (totals[key] or ZERO) + g.amount
            gl_by_account[(g.account_id, m)] += g.amount
        for cls, key in OPERATING.items():
            if totals[key] is None:
                issues.append(
                    Issue(
                        "missing_category",
                        f"{m}: the source has no {cls.value} row. A category with no activity "
                        "needs an explicit zero row; it is never assumed to be zero.",
                        True,
                    )
                )
        by_month[m] = totals

    metrics: list[dict[str, Any]] = []
    for m in months:
        t = by_month[m]
        revenue = t["revenue"] or ZERO
        cos = t["cost_of_services"] or ZERO
        opex = t["operating_expense"] or ZERO
        profit = revenue - cos - opex
        metrics.append(
            {
                "period": m,
                "revenue": revenue,
                "cost_of_services": cos,
                "operating_expense": opex,
                "gross_profit": revenue - cos,
                "total_operating_cost": cos + opex,
                "operating_profit": profit,
                "margin_pct": _q(margin(profit, revenue)),
                "other_income": t["other_income"],
                "other_expense": t["other_expense"],
            }
        )
    if any(r["other_income"] is not None or r["other_expense"] is not None for r in metrics):
        caveats.append(
            "The source has OtherIncome / OtherExpense accounts: they are shown separately and "
            "left out of operating revenue and cost (this is not a net income calculation)."
        )

    txns = [t for t in doc.transactions if _in_unit(t, unit) and t.period in months]
    skipped = [t for t in txns if t.status != "Posted"]
    if skipped:
        caveats.append(
            f"{len(skipped)} draft or voided transaction(s) in the period are left out: drivers "
            "use Posted transactions only."
        )
    posted = [t for t in txns if t.status == "Posted" and t.account_id in accounts]

    changes = []
    for prev, cur in pairwise(metrics):
        changes.append(_change(prev, cur, accounts, posted, gl_by_account, issues))

    yoy = []
    all_lines = [g for g in doc.gl_lines if _in_unit(g, unit)]
    for m in months:
        py = prior_year(m)
        rows = [g for g in all_lines if g.period == py]
        income = [g for g in rows if accounts[g.account_id].classification == AccountClass.INCOME]
        if not income:
            continue  # YoY only for sourced prior-year months
        revenue_py = sum((g.amount for g in income), ZERO)
        current = next(r for r in metrics if r["period"] == m)
        yoy.append(
            {
                "period": m,
                "prior_period": py,
                "revenue_prior": revenue_py,
                "revenue_pct": pct_change(current["revenue"], revenue_py),
            }
        )

    return {
        "months": months,
        "business_unit": unit,
        "currency": doc.currency,
        "basis": doc.basis.value,
        "metrics": metrics,
        "changes": changes,
        "yoy": yoy,
        "seasonality": _seasonality(metrics),
        "mapping": _mapping(accounts, lines, months),
        "issues": [i.as_dict() for i in issues],
        "caveats": caveats,
    }


def _change(
    prev: dict[str, Any],
    cur: dict[str, Any],
    accounts: dict[str, Any],
    posted: list[Transaction],
    gl_by_account: dict[tuple[str, str], Decimal],
    issues: list[Issue],
) -> dict[str, Any]:
    p0, p1 = prev["period"], cur["period"]
    m0, m1 = (
        margin(prev["operating_profit"], prev["revenue"]),
        margin(cur["operating_profit"], cur["revenue"]),
    )
    revenue_delta = cur["revenue"] - prev["revenue"]
    cos_delta = cur["cost_of_services"] - prev["cost_of_services"]
    opex_delta = cur["operating_expense"] - prev["operating_expense"]
    profit_delta = cur["operating_profit"] - prev["operating_profit"]
    revenue_pct = pct_change(cur["revenue"], prev["revenue"])

    # Every operating account: GL delta vs the Posted transactions' delta
    per_account: dict[str, dict[str, Any]] = {}
    for (account_id, period), amount in gl_by_account.items():
        if period not in (p0, p1) or accounts[account_id].classification not in OPERATING:
            continue
        entry = per_account.setdefault(account_id, {"gl": {p0: ZERO, p1: ZERO}, "txns": []})
        entry["gl"][period] += amount
    for t in posted:
        if t.period not in (p0, p1) or accounts[t.account_id].classification not in OPERATING:
            continue
        entry = per_account.setdefault(t.account_id, {"gl": {p0: ZERO, p1: ZERO}, "txns": []})
        entry["txns"].append(t)

    unexplained = []
    revenue_contrib: dict[str, list[Transaction]] = defaultdict(list)
    cost_accounts = []
    for account_id, entry in per_account.items():
        acct = accounts[account_id]
        gl_delta = entry["gl"][p1] - entry["gl"][p0]
        txn_delta = sum((t.amount if t.period == p1 else -t.amount for t in entry["txns"]), ZERO)
        diff = gl_delta - txn_delta
        if diff != 0:
            unexplained.append(
                {
                    "account_id": account_id,
                    "account": acct.name,
                    "gl_delta": gl_delta,
                    "transaction_delta": txn_delta,
                    "difference": diff,
                }
            )
            issues.append(
                Issue(
                    "unexplained_delta",
                    f"{p0} → {p1}: {acct.name} moved {gl_delta} in the GL but its Posted "
                    f"transactions explain {txn_delta} (difference {diff}). Correct the source "
                    "evidence; a note can't settle it.",
                    True,
                )
            )
        if acct.classification == AccountClass.INCOME:
            for t in entry["txns"]:
                revenue_contrib[t.counterparty or "(no customer)"].append(t)
        else:
            cost_accounts.append(
                {
                    "account_id": account_id,
                    "account": acct.name,
                    "classification": acct.classification.value,
                    "prior": entry["gl"][p0],
                    "current": entry["gl"][p1],
                    "change": gl_delta,
                    "contributors": _contributors(_group(entry["txns"]), p1),
                }
            )
    cost_accounts.sort(key=lambda a: (-abs(a["change"]), a["account"]))
    exact = _q(m1 - m0) if m0 is not None and m1 is not None else None
    displayed = round(m1, 1) - round(m0, 1) if m0 is not None and m1 is not None else None
    return {
        "from": p0,
        "to": p1,
        "revenue": {"change": revenue_delta, "pct": revenue_pct},
        "cost_of_services": {
            "change": cos_delta,
            "pct": pct_change(cur["cost_of_services"], prev["cost_of_services"]),
        },
        "operating_expense": {
            "change": opex_delta,
            "pct": pct_change(cur["operating_expense"], prev["operating_expense"]),
        },
        "total_operating_cost": {
            "change": cos_delta + opex_delta,
            "pct": pct_change(cur["total_operating_cost"], prev["total_operating_cost"]),
        },
        "operating_profit": {
            "change": profit_delta,
            "pct": pct_change(cur["operating_profit"], prev["operating_profit"]),
        },
        # Exact (unrounded margins) and as displayed (rounded margins subtracted): both kept
        "margin_pp_exact": exact,
        "margin_pp_displayed": displayed,
        "outlier": revenue_pct is not None and abs(revenue_pct) >= OUTLIER_PCT,
        "bridge": {
            "from_profit": prev["operating_profit"],
            "revenue": revenue_delta,
            "cost_of_services": -cos_delta,
            "operating_expense": -opex_delta,
            "to_profit": cur["operating_profit"],
            # profit change = revenue change - cost of services change - opex change
            "reconciles": prev["operating_profit"] + revenue_delta - cos_delta - opex_delta
            == cur["operating_profit"],
        },
        "revenue_drivers": _contributors(revenue_contrib, p1),
        "cost_drivers": cost_accounts,
        "unexplained": unexplained,
    }


def _group(txns: list[Transaction]) -> dict[str, list[Transaction]]:
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        groups[t.counterparty or "(no counterparty)"].append(t)
    return groups


def _contributors(groups: dict[str, list[Transaction]], current: str) -> list[dict[str, Any]]:
    """Who moved the figure: current-period amounts minus prior-period amounts, with the
    transactions (IDs, documents, GL lines, periods) behind each; the smallest folded."""
    rows: list[dict[str, Any]] = []
    for name, txns in groups.items():
        delta = sum((t.amount if t.period == current else -t.amount for t in txns), ZERO)
        rows.append(
            {
                "counterparty": name,
                "change": delta,
                "transactions": [
                    {
                        "id": t.id,
                        "type": t.type,
                        "date": t.date,
                        "period": t.period,
                        "amount": t.amount,
                        "document_ref": t.document_ref,
                        "gl_line_id": t.gl_line_id,
                    }
                    for t in sorted(txns, key=lambda t: (t.period, t.date, t.id))
                ],
            }
        )
    rows.sort(key=lambda r: (-abs(r["change"]), r["counterparty"]))
    if len(rows) <= TOP_CONTRIBUTORS:
        return rows
    head, rest = rows[: TOP_CONTRIBUTORS - 1], rows[TOP_CONTRIBUTORS - 1 :]
    others = {
        "counterparty": f"{len(rest)} others",
        "change": sum((r["change"] for r in rest), ZERO),
        "transactions": [t for r in rest for t in r["transactions"]][:50],
    }
    return [*head, others]


def _seasonality(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Descriptive seasonal revenue indices: only with 24+ selected months and every calendar
    month seen at least twice. Not a forecast."""
    if len(metrics) < SEASONAL_MIN_MONTHS:
        return None
    by_calendar: dict[str, list[Decimal]] = defaultdict(list)
    for r in metrics:
        by_calendar[r["period"][5:]].append(r["revenue"])
    if len(by_calendar) < 12 or any(len(v) < 2 for v in by_calendar.values()):
        return None
    overall = sum((r["revenue"] for r in metrics), ZERO) / len(metrics)
    if overall == 0:
        return None
    return {
        "observations": len(metrics),
        "indices": {
            month: _q(100 * (sum(v, ZERO) / len(v)) / overall)
            for month, v in sorted(by_calendar.items())
        },
    }


def _mapping(
    accounts: dict[str, Any], lines: list[GlLine], months: list[str]
) -> list[dict[str, Any]]:
    """The accounts the figures use and where each one is counted (for the mapping review)."""
    used = sorted({g.account_id for g in lines if g.period in months})
    out = []
    for account_id in used:
        acct = accounts[account_id]
        cls = acct.classification
        out.append(
            {
                "account_id": account_id,
                "account": acct.name,
                "number": acct.number,
                "classification": cls.value,
                "counted_as": OPERATING.get(cls) or NON_OPERATING.get(cls) or "not in the P&L",
            }
        )
    return out


def latest_change(state: dict[str, Any]) -> dict[str, Any] | None:
    changes: list[dict[str, Any]] = state.get("changes", [])
    return changes[-1] if changes else None


def blocking_issues(state: dict[str, Any]) -> list[str]:
    return [str(i["detail"]) for i in state.get("issues", []) if i.get("blocking")]


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(CENT)
