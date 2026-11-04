"""The 13-week cash forecast (TDD section 9), deterministic: no AI, no accounting.

Opening cash must be cleared, dated to the snapshot, and equal both the QuickBooks cash
balance and an explicitly supplied reconciliation balance (never defaulted from cash). For
each day over 91 days: cash = prior cash + expected receipts - approved outflows, where an
expected receipt is its nominal amount x the approved probability. Headroom = cash - policy
buffer; shortfall = max(0, buffer - cash). Thirteen seven-day summaries give inflow, outflow,
ending cash, minimum cash and maximum shortfall; the horizon's first breach and maximum
shortfall are kept too. Scenarios only move parts of existing events to explicit dates.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.snapshots.contract import SnapshotDocument

HORIZON_DAYS = 91
WEEKS = 13
ZERO = Decimal(0)
CENT = Decimal("0.01")


def opening_cash(doc: SnapshotDocument) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The opening position and its blocking problems (raise when it can't be used at all)."""
    cash = doc.cash_position
    if cash is None:
        raise CaseSelectionError("The source has no cash position: import the bank balance.")
    if cash.reconciliation_balance is None:
        raise CaseSelectionError(
            "The source has no QuickBooks reconciliation balance: it is never taken from the "
            "cash balance. Import a source that states it."
        )
    issues = []

    def issue(code: str, detail: str) -> None:
        issues.append({"code": code, "detail": detail, "blocking": True})

    if not cash.cleared:
        issue("cash_not_cleared", "The opening bank balance isn't cleared: use cleared cash only.")
    if cash.as_of != doc.as_of:
        issue(
            "cash_date",
            f"The cash position is dated {cash.as_of}, the snapshot {doc.as_of}: they must match.",
        )
    if cash.bank_balance != cash.quickbooks_cash_balance:
        issue(
            "cash_vs_quickbooks",
            f"Bank {cash.bank_balance} doesn't equal the QuickBooks cash balance "
            f"{cash.quickbooks_cash_balance}.",
        )
    if cash.bank_balance != cash.reconciliation_balance:
        issue(
            "cash_vs_reconciliation",
            f"Bank {cash.bank_balance} doesn't equal the QuickBooks reconciliation balance "
            f"{cash.reconciliation_balance}.",
        )
    return (
        {
            "as_of": cash.as_of,
            "bank_balance": cash.bank_balance,
            "quickbooks_cash_balance": cash.quickbooks_cash_balance,
            "reconciliation_balance": cash.reconciliation_balance,
            "policy_buffer": cash.policy_buffer,
            "cleared": cash.cleared,
            "proof_reference": cash.proof_reference,
        },
        issues,
    )


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def forecast(
    start: date,
    opening: Decimal,
    buffer: Decimal,
    receipts: list[dict[str, Any]],
    outflows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Day 1 is the day after `start` (the snapshot date). Events outside the 91 days don't
    count. receipts: {"date", "expected"}; outflows: {"date", "amount"}."""
    end = start + timedelta(days=HORIZON_DAYS)
    inflow_on: dict[date, Decimal] = {}
    outflow_on: dict[date, Decimal] = {}
    for r in receipts:
        d = date.fromisoformat(str(r["date"]))
        if start < d <= end:
            inflow_on[d] = inflow_on.get(d, ZERO) + _dec(r["expected"])
    for o in outflows:
        d = date.fromisoformat(str(o["date"]))
        if start < d <= end:
            outflow_on[d] = outflow_on.get(d, ZERO) + _dec(o["amount"])

    days: list[dict[str, Any]] = []
    cash = opening
    first_breach: date | None = None
    max_shortfall = ZERO
    for n in range(1, HORIZON_DAYS + 1):
        d = start + timedelta(days=n)
        inflow, outflow = inflow_on.get(d, ZERO), outflow_on.get(d, ZERO)
        cash = cash + inflow - outflow
        shortfall = max(ZERO, buffer - cash)
        if shortfall > 0 and first_breach is None:
            first_breach = d
        max_shortfall = max(max_shortfall, shortfall)
        days.append(
            {
                "date": d,
                "inflow": inflow,
                "outflow": outflow,
                "cash": cash,
                "headroom": cash - buffer,
                "shortfall": shortfall,
            }
        )
    weeks = []
    for w in range(WEEKS):
        chunk = days[w * 7 : (w + 1) * 7]
        weeks.append(
            {
                "week": w + 1,
                "from": chunk[0]["date"],
                "to": chunk[-1]["date"],
                "inflow": sum((x["inflow"] for x in chunk), ZERO),
                "outflow": sum((x["outflow"] for x in chunk), ZERO),
                "ending_cash": chunk[-1]["cash"],
                "minimum_cash": min(x["cash"] for x in chunk),
                "max_shortfall": max(x["shortfall"] for x in chunk),
            }
        )
    return {
        "start": start,
        "end": end,
        "opening": opening,
        "buffer": buffer,
        "inflow": sum((x["inflow"] for x in days), ZERO),
        "outflow": sum((x["outflow"] for x in days), ZERO),
        "ending_cash": cash,
        "ending_shortfall": max(ZERO, buffer - cash),
        "minimum_cash": min(x["cash"] for x in days),
        "first_breach": first_breach,
        "max_shortfall": max_shortfall,
        "weeks": weeks,
        "days": days,
    }


def events(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Base events: reviewed, included receipts (expected = nominal x probability) and the
    approved outflows."""
    receipts = [
        {
            "id": r["id"],
            "date": r["date"],
            "amount": _dec(r["amount"]),
            "probability": _dec(r["review"]["probability"]),
            "expected": (_dec(r["amount"]) * _dec(r["review"]["probability"])).quantize(CENT),
        }
        for r in state.get("receipts", [])
        if not r.get("rejected") and (r.get("review") or {}).get("include")
    ]
    outflows = [
        {"id": o["id"], "date": o["date"], "amount": _dec(o["amount"])}
        for o in state.get("outflows", [])
        if o.get("approved")
    ]
    return receipts, outflows


def apply_shifts(
    receipts: list[dict[str, Any]], outflows: list[dict[str, Any]], shifts: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Move the shifted part of each event to its new date: the totals never change."""
    rec = [dict(r) for r in receipts]
    out = [dict(o) for o in outflows]
    for s in shifts:
        moved = _dec(s["amount"])
        for r in list(rec):
            if r["id"] == s["event_id"]:
                expected = (moved * r["probability"]).quantize(CENT)
                r["amount"] -= moved
                r["expected"] -= expected
                rec.append(
                    {
                        **r,
                        "id": f"{r['id']}>{s['id']}",
                        "date": s["to_date"],
                        "amount": moved,
                        "expected": expected,
                    }
                )
                break
        else:
            for o in list(out):
                if o["id"] == s["event_id"]:
                    o["amount"] -= moved
                    out.append(
                        {**o, "id": f"{o['id']}>{s['id']}", "date": s["to_date"], "amount": moved}
                    )
                    break
    return rec, out


def compute(state: dict[str, Any]) -> dict[str, Any]:
    """Base, Optimistic and Stress results for the state's current events and shifts."""
    start = date.fromisoformat(str(state["as_of"]))
    opening = _dec(state["cash"]["bank_balance"])
    buffer = _dec(state["cash"]["policy_buffer"])
    receipts, outflows = events(state)
    results = {"base": forecast(start, opening, buffer, receipts, outflows)}
    for name in ("optimistic", "stress"):
        r, o = apply_shifts(receipts, outflows, (state.get("scenarios") or {}).get(name, []))
        results[name] = forecast(start, opening, buffer, r, o)
    return results
