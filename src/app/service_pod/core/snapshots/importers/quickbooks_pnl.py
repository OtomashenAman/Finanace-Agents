"""The P&L evidence FP&A needs, read from a connected QuickBooks Online company at snapshot
time (the agents' sync isn't involved): each account's monthly amount (ProfitAndLoss by
month) and the transactions behind it (ProfitAndLossDetail). Both reports are read-only.

QuickBooks reports only contain posted transactions, with amounts as the P&L presents them
(income and costs positive, credit memos negative) and net of sales tax. Each P&L account
row gives a GL line for every month of the range, a blank cell an explicit zero, so a
category that does appear is never missing a month. A GL line cites the detail rows of its
account and month; whether they add up is the FP&A engine's check, not this importer's.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from src.app.data_sources.records import month_end
from src.app.service_pod.core.snapshots.contract import AccountClass, Basis, GlLine, Transaction

PNL_MONTHS = 13  # the latest month and the same month a year before (year-on-year)
PNL_CLASSES = {
    AccountClass.INCOME,
    AccountClass.COST_OF_GOODS_SOLD,
    AccountClass.EXPENSE,
    AccountClass.OTHER_INCOME,
    AccountClass.OTHER_EXPENSE,
}


class ReportApi(Protocol):
    async def report(self, name: str, **params: str) -> dict[str, Any]: ...


@dataclass
class PnlReports:
    by_month: dict[str, Any]
    detail: dict[str, Any]
    start: str  # YYYY-MM
    end: str


def last_complete_months(today: date, months: int = PNL_MONTHS) -> tuple[str, str]:
    year, month = today.year, today.month
    year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    end = f"{year:04d}-{month:02d}"
    for _ in range(months - 1):
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return f"{year:04d}-{month:02d}", end


async def fetch_pnl(api: ReportApi, today: date, basis: Basis) -> PnlReports:
    start, end = last_complete_months(today)
    params = {
        "start_date": f"{start}-01",
        "end_date": month_end(end).isoformat(),
        "accounting_method": basis.value,
    }
    by_month = await api.report("ProfitAndLoss", summarize_column_by="Month", **params)
    detail = await api.report("ProfitAndLossDetail", **params)
    return PnlReports(by_month=by_month, detail=detail, start=start, end=end)


def _walk(
    rows: list[dict[str, Any]],
    found: list[tuple[dict[str, Any], dict[str, Any] | None]],
    header: dict[str, Any] | None,
) -> None:
    """Every Data row with the account section header it sits under."""
    for row in rows:
        section = (row.get("Header") or {}).get("ColData")
        inner = (row.get("Rows") or {}).get("Row", [])
        if section and section[0].get("value"):
            # a parent account's own amounts can sit on its header row
            found.append((row["Header"], header))
            _walk(inner, found, section[0])
        elif inner:
            _walk(inner, found, header)
        elif row.get("ColData"):
            found.append((row, header))


def _rows(report: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    found: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    _walk((report.get("Rows") or {}).get("Row", []), found, None)
    return found


def _money(cell: dict[str, Any] | None) -> Decimal | None:
    raw = str((cell or {}).get("value") or "").replace(",", "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _month_columns(report: dict[str, Any]) -> list[tuple[int, str]]:
    """(cell index, YYYY-MM) for each month column; Total and the label column skipped."""
    out = []
    for i, column in enumerate((report.get("Columns") or {}).get("Column", [])):
        meta = {m.get("Name"): m.get("Value") for m in column.get("MetaData") or []}
        start = meta.get("StartDate")
        if start and (meta.get("EndDate") or "")[:7] == start[:7]:
            out.append((i, start[:7]))
    return out


def _detail_columns(report: dict[str, Any]) -> dict[str, int]:
    keys: dict[str, int] = {}
    for i, column in enumerate((report.get("Columns") or {}).get("Column", [])):
        meta = {m.get("Name"): m.get("Value") for m in column.get("MetaData") or []}
        if meta.get("ColKey"):
            keys[str(meta["ColKey"])] = i
    return keys


def build_pnl(
    reports: PnlReports, accounts: dict[str, AccountClass], names: dict[str, str]
) -> tuple[list[GlLine], list[Transaction], list[str]]:
    """GL lines and transactions (and notes on what couldn't be placed) from the reports.
    `accounts`: account id -> class; `names`: lower-case account name -> id."""
    notes: list[str] = []

    def account_of(cell: dict[str, Any] | None) -> str | None:
        if not cell:
            return None
        if cell.get("id") and str(cell["id"]) in accounts:
            return str(cell["id"])
        return names.get(str(cell.get("value") or "").strip().lower())

    months = _month_columns(reports.by_month)
    amounts: dict[tuple[str, str], Decimal] = {}
    for row, _ in _rows(reports.by_month):
        cells = row.get("ColData") or []
        account = account_of(cells[0] if cells else None)
        if account is None or accounts[account] not in PNL_CLASSES:
            continue
        for index, period in months:
            value = _money(cells[index]) if index < len(cells) else None
            key = (account, period)
            amounts[key] = amounts.get(key, Decimal(0)) + (value or Decimal(0))

    columns = _detail_columns(reports.detail)
    needed = {"tx_date", "txn_type", "subt_nat_amount"}
    rows: list[dict[str, Any]] = []
    if not needed <= set(columns):
        notes.append("The P&L detail report has no date / type / amount columns: no transactions.")
    else:
        unplaced = 0
        for row, header in _rows(reports.detail):
            cells = row.get("ColData") or []
            if len(cells) <= max(columns.values()):
                continue
            when = str(cells[columns["tx_date"]].get("value") or "")
            amount = _money(cells[columns["subt_nat_amount"]])
            kind = cells[columns["txn_type"]]
            if len(when) != 10 or amount is None or not kind.get("id"):
                continue  # section totals and headers
            account = account_of(header)
            if account is None or accounts[account] not in PNL_CLASSES:
                unplaced += 1
                continue
            period = when[:7]
            if (account, period) not in amounts:
                unplaced += 1
                continue
            name = cells[columns["name"]].get("value") if "name" in columns else None
            doc = cells[columns["doc_num"]].get("value") if "doc_num" in columns else None
            rows.append(
                {
                    "key": f"{kind.get('value') or 'Txn'}-{kind['id']}",
                    "type": str(kind.get("value") or "Transaction")[:200],
                    "date": date.fromisoformat(when),
                    "period": period,
                    "account": account,
                    "amount": amount,
                    "counterparty": (str(name)[:200] if name else None),
                    "document_ref": (str(doc)[:4000] if doc else None),
                }
            )
        if unplaced:
            notes.append(
                f"{unplaced} P&L detail row(s) couldn't be placed on an account and month."
            )

    # One id per row: the transaction's own, ":n" when it touches several lines
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["key"]] = counts.get(r["key"], 0) + 1
    seen: dict[str, int] = {}
    cited: dict[tuple[str, str], list[str]] = {}
    transactions = []
    for r in rows:
        seen[r["key"]] = seen.get(r["key"], 0) + 1
        txn_id = r["key"] if counts[r["key"]] == 1 else f"{r['key']}:{seen[r['key']]}"
        gl_id = f"QB-PL-{r['account']}-{r['period']}"
        cited.setdefault((r["account"], r["period"]), []).append(txn_id)
        transactions.append(
            Transaction(
                id=txn_id,
                date=r["date"],
                period=r["period"],
                type=r["type"],
                counterparty=r["counterparty"],
                account_id=r["account"],
                amount=r["amount"],
                status="Posted",
                gl_line_id=gl_id,
                document_ref=r["document_ref"],
            )
        )
    gl_lines = [
        GlLine(
            id=f"QB-PL-{account}-{period}",
            account_id=account,
            period=period,
            amount=amount,
            report_id=f"ProfitAndLoss {reports.start}..{reports.end}",
            transaction_ids=cited.get((account, period), []),
        )
        for (account, period), amount in sorted(amounts.items())
    ]
    return gl_lines, transactions, notes
