"""The Service POD test workbooks in docs/sample-uploads/service-pod/ (uv run poe pod-samples).

One fictional company (SYNTHETIC_DEMO) built from the V1.1 deck's own figures, so every
workflow has its data: AR aging and the Harbor case (slides 8-12), WIRE-2901 (15-18), the
six-month P&L with its invoice and cost drivers (21-27), the 13-week treasury example
(31-36) and the September management pack (41-42). Variants show a posting verified, a
posting that doesn't match, and a file the import refuses.
"""

from collections.abc import Iterable
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "docs" / "sample-uploads" / "service-pod"
Row = dict[str, Any]

COMPANY: Row = {
    "Company ID": "DEMO-ESOL",
    "Company Name": "E-Solutions Demo Co",
    "Entity": "US01",
    "Currency": "USD",
    "Basis": "Accrual",
    "As of": date(2026, 11, 5),
    "Provenance": "SYNTHETIC_DEMO",
    "Source reference": "Deck V1.1 test workbook (fictional, not client accounting)",
}

CUSTOMERS = [
    {
        "ID": "C1",
        "Name": "Harbor Distribution",
        "Email": "ap@harbor.example",
        "Contact": "Harbor AP",
    },
    {
        "ID": "C2",
        "Name": "Cobalt Systems",
        "Email": "ap@cobalt.example",
        "Contact": "Cobalt Finance",
    },
    {
        "ID": "C3",
        "Name": "Northwind Services",
        "Email": "ap@northwind.example",
        "Contact": "Northwind AP",
    },
    {
        "ID": "C4",
        "Name": "Futura Technologies",
        "Email": "ap@futura.example",
        "Contact": "Futura AP",
    },
    {
        "ID": "C5",
        "Name": "Bluewave Retail",
        "Email": "ap@bluewave.example",
        "Contact": "Bluewave AP",
    },
]


def _inv(
    i: str,
    num: str,
    cust: str,
    d: date,
    due: date,
    amount: int,
    balance: int,
    terms: str = "Net 30",
) -> Row:
    return {
        "ID": i,
        "Number": num,
        "Customer ID": cust,
        "Date": d,
        "Due Date": due,
        "Amount": amount,
        "Balance": balance,
        "Terms": terms,
    }


INVOICES = [
    # AR portfolio (as of Nov 5): Harbor 25k / 31-35 days, Cobalt 48.5k / 19, Northwind 12.8k / 8
    _inv("I101", "INV-101", "C1", date(2026, 9, 1), date(2026, 10, 1), 15000, 15000),
    _inv("I102", "INV-102", "C1", date(2026, 9, 5), date(2026, 10, 5), 10000, 10000),
    _inv("I201", "INV-201", "C2", date(2026, 9, 17), date(2026, 10, 17), 48500, 48500),
    _inv("I301", "INV-301", "C3", date(2026, 9, 28), date(2026, 10, 28), 12800, 12800),
    _inv("I501", "INV-501", "C5", date(2026, 7, 2), date(2026, 8, 1), 9000, 9000),  # 90+ days
    # Treasury receipts not yet due (MSA-linked, slide 32)
    _inv("I401", "INV-401", "C2", date(2026, 10, 9), date(2026, 11, 8), 90000, 90000),
    _inv("I402", "INV-402", "C2", date(2026, 10, 16), date(2026, 11, 25), 60000, 60000),
    # Paid: history and September's revenue drivers (slide 24)
    _inv("I100", "INV-100", "C1", date(2026, 7, 1), date(2026, 7, 31), 5000, 0),
    _inv("I300", "INV-300", "C3", date(2026, 9, 2), date(2026, 10, 2), 4000, 0),
    _inv("I411", "INV-411", "C4", date(2026, 9, 10), date(2026, 10, 10), 42000, 0),
    _inv("I416", "INV-416", "C4", date(2026, 9, 22), date(2026, 10, 22), 26000, 0),
]


def _pay(
    i: str, cust: str, d: date, amount: int, ref: str, applied: list[tuple[str, int]]
) -> list[Row]:
    base = {
        "ID": i,
        "Customer ID": cust,
        "Date": d,
        "Amount": amount,
        "Currency": "USD",
        "Reference": ref,
    }
    return [{**base, "Invoice ID": inv, "Applied": amt} for inv, amt in applied] or [base]


PAYMENTS = [
    *_pay("PMT-50", "C1", date(2026, 8, 14), 5000, "CHK-1001", [("I100", 5000)]),
    *_pay("PMT-61", "C3", date(2026, 11, 3), 4000, "CHK-2210", [("I300", 4000)]),
    *_pay(
        "PMT-70", "C4", date(2026, 10, 12), 68000, "WIRE-2800", [("I411", 42000), ("I416", 26000)]
    ),
]

BANK_RECEIPTS = [
    # WIRE-2901: the deck's $9,000 from Harbor (slides 15-18)
    {
        "Reference": "WIRE-2901",
        "Payer": "Harbor Distribution",
        "Date": date(2026, 11, 5),
        "Amount": 9000,
        "Currency": "USD",
        "Cleared": "yes",
        "Proof": "Statement 2026-11-05 line 14",
    },
    {
        "Reference": "WIRE-2950",
        "Payer": "Northwind Services Inc.",
        "Date": date(2026, 11, 4),
        "Amount": 12800,
        "Currency": "USD",
        "Cleared": "yes",
        "Proof": "Statement 2026-11-04 line 3",
    },
    # Not cleared yet: can't be applied
    {
        "Reference": "ACH-3001",
        "Payer": "Cobalt Systems",
        "Date": date(2026, 11, 5),
        "Amount": 20000,
        "Currency": "USD",
        "Cleared": "no",
        "Proof": None,
    },
    # The payer isn't a customer name: needs the preparer's evidence
    {
        "Reference": "WIRE-3100",
        "Payer": "HDI Holdings",
        "Date": date(2026, 11, 3),
        "Amount": 700,
        "Currency": "USD",
        "Cleared": "yes",
        "Proof": "Statement 2026-11-03 line 9",
    },
    # Same amount and customer as PMT-61 two days ago: a possible duplicate
    {
        "Reference": "CHK-2211",
        "Payer": "Northwind Services",
        "Date": date(2026, 11, 4),
        "Amount": 4000,
        "Currency": "USD",
        "Cleared": "yes",
        "Proof": "Statement 2026-11-04 line 5",
    },
    # Already recorded as PMT-50: never shows as unapplied
    {
        "Reference": "CHK-1001",
        "Payer": "Harbor Distribution",
        "Date": date(2026, 8, 14),
        "Amount": 5000,
        "Currency": "USD",
        "Cleared": "yes",
        "Proof": "Statement 2026-08-14 line 2",
    },
]

ACCOUNTS = [
    {"ID": "A100", "Name": "Operating Bank", "Number": "1000", "Classification": "Asset"},
    {"ID": "A110", "Name": "Accounts Receivable", "Number": "1100", "Classification": "Asset"},
    {"ID": "A200", "Name": "Accounts Payable", "Number": "2000", "Classification": "Liability"},
    {"ID": "A300", "Name": "Retained Earnings", "Number": "3000", "Classification": "Equity"},
    {"ID": "A400", "Name": "Consulting Revenue", "Number": "4000", "Classification": "Income"},
    {
        "ID": "A500",
        "Name": "Subcontractor Costs",
        "Number": "5000",
        "Classification": "CostOfGoodsSold",
    },
    {"ID": "A600", "Name": "Payroll", "Number": "6000", "Classification": "Expense"},
    {"ID": "A610", "Name": "Cloud and Tools", "Number": "6100", "Classification": "Expense"},
    {"ID": "A620", "Name": "Other Operating Costs", "Number": "6200", "Classification": "Expense"},
]

# Slide 21 ($000): revenue, cost of services and operating expenses Apr-Sep; operating
# expenses split so Aug -> Sep shows payroll +7, cloud +3, other +2 (slide 25)
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
REVENUE = {  # month -> [(counterparty, document, $000)]
    "2026-04": [("Harbor Distribution", "REV-04-H", 220), ("Cobalt Systems", "REV-04-C", 200)],
    "2026-05": [("Harbor Distribution", "REV-05-H", 230), ("Cobalt Systems", "REV-05-C", 210)],
    "2026-06": [("Harbor Distribution", "REV-06-H", 240), ("Cobalt Systems", "REV-06-C", 220)],
    "2026-07": [("Harbor Distribution", "REV-07-H", 235), ("Cobalt Systems", "REV-07-C", 220)],
    "2026-08": [("Harbor Distribution", "REV-08-H", 250), ("Cobalt Systems", "REV-08-C", 230)],
    # +60k: new enterprise invoice INV-411 +42, expanded services INV-416 +26, Cobalt -8
    "2026-09": [
        ("Harbor Distribution", "REV-09-H", 250),
        ("Cobalt Systems", "REV-09-C", 222),
        ("Futura Technologies", "INV-411", 42),
        ("Futura Technologies", "INV-416", 26),
    ],
}
COSTS = {  # account -> $000 per month
    "A500": [252, 264, 276, 282, 288, 318],
    "A600": [70, 72, 77, 80, 83, 90],
    "A610": [20, 20, 22, 22, 23, 26],
    "A620": [15, 16, 17, 18, 19, 21],
}
COST_PARTY = {
    "A500": ("Bill", "Apex Contractors"),
    "A600": ("JournalEntry", "Payroll run"),
    "A610": ("Bill", "CloudCo"),
    "A620": ("Expense", "Various vendors"),
}


def ledger() -> tuple[list[Row], list[Row]]:
    """GL lines and the posted transactions behind them, citing each other both ways."""
    gl_lines: list[Row] = []
    txns: list[Row] = []
    for m, month in enumerate(MONTHS):
        year, mon = (int(x) for x in month.split("-"))
        entries: list[tuple[str, str, str, str, int]] = [
            ("A400", "Invoice", party, doc, k) for party, doc, k in REVENUE[month]
        ]
        entries += [
            (acc, COST_PARTY[acc][0], COST_PARTY[acc][1], f"{acc}-{month}", per[m])
            for acc, per in COSTS.items()
        ]
        by_account: dict[str, list[str]] = {}
        for n, (acc, kind, party, doc, k) in enumerate(entries, start=1):
            txn_id = f"T-{month}-{n:02d}"
            by_account.setdefault(acc, []).append(txn_id)
            txns.append(
                {
                    "ID": txn_id,
                    "Date": date(year, mon, 15),
                    "Period": month,
                    "Type": kind,
                    "Counterparty": party,
                    "Account ID": acc,
                    "Amount": k * 1000,
                    "Tax": 0,
                    "Status": "Posted",
                    "GL Line ID": f"GL-{month}-{acc}",
                    "Document": doc,
                }
            )
        for acc, ids in by_account.items():
            total = sum(t["Amount"] for t in txns if t["ID"] in ids)
            gl_lines.append(
                {
                    "ID": f"GL-{month}-{acc}",
                    "Account ID": acc,
                    "Period": month,
                    "Amount": total,
                    "Report ID": f"PL-{month}",
                    "Transaction IDs": ", ".join(ids),
                }
            )
    return gl_lines, txns


CONTRACTS = [
    {
        "ID": "MSA-COBALT",
        "Customer ID": "C2",
        "Invoice IDs": "I401, I402",
        "Terms": "Payment within 30 days of approved timesheets",
        "Status": "Active",
    },
    {
        "ID": "MSA-HARBOR",
        "Customer ID": "C1",
        "Invoice IDs": "I101, I102",
        "Terms": "Net 30 from invoice date",
        "Status": "Active",
    },
]
PLANNED_OUTFLOWS = [  # 300k approved (slide 31); one not approved yet
    {
        "ID": "O1",
        "Date": date(2026, 11, 15),
        "Amount": 180000,
        "Category": "Payroll",
        "Approved": "yes",
        "Approval Ref": "PAY-NOV",
    },
    {
        "ID": "O2",
        "Date": date(2026, 11, 25),
        "Amount": 120000,
        "Category": "Suppliers",
        "Approved": "yes",
        "Approval Ref": "AP-RUN-47",
    },
    {
        "ID": "O3",
        "Date": date(2026, 12, 10),
        "Amount": 40000,
        "Category": "Office fit-out",
        "Approved": "no",
        "Approval Ref": None,
    },
]
CASH_POSITION = [
    {
        "As of": date(2026, 11, 5),
        "Bank balance": 250000,
        "QuickBooks cash": 250000,
        "Reconciliation balance": 250000,
        "Policy buffer": 125000,
        "Cleared": "yes",
        "Proof": "Bank statement 2026-11-05",
    }
]
# Equity grows by each month's operating profit (Aug 67k, Sep 85k)
BALANCE_SHEETS = [
    {
        "Period": "2026-07",
        "Assets": 1180000,
        "Liabilities": 447000,
        "Equity": 733000,
        "Report ID": "BS-2026-07",
    },
    {
        "Period": "2026-08",
        "Assets": 1250000,
        "Liabilities": 450000,
        "Equity": 800000,
        "Report ID": "BS-2026-08",
    },
    {
        "Period": "2026-09",
        "Assets": 1320000,
        "Liabilities": 435000,
        "Equity": 885000,
        "Report ID": "BS-2026-09",
    },
]
CHECKS = "Bank reconciliation; AR subledger tie-out; Accrual cutoff"
CLOSE_STATUS = [
    {"Period": "2026-07", "Status": "Closed", "Required checks": CHECKS},
    {"Period": "2026-08", "Status": "Closed", "Required checks": CHECKS},
    {"Period": "2026-09", "Status": "Closed", "Required checks": CHECKS},
]


def full() -> dict[str, list[Row]]:
    gl_lines, txns = ledger()
    return {
        "Company": [COMPANY],
        "Customers": CUSTOMERS,
        "Invoices": INVOICES,
        "Payments": PAYMENTS,
        "Bank receipts": BANK_RECEIPTS,
        "Accounts": ACCOUNTS,
        "GL lines": gl_lines,
        "Transactions": txns,
        "Contracts": CONTRACTS,
        "Planned outflows": PLANNED_OUTFLOWS,
        "Cash position": CASH_POSITION,
        "Balance sheets": BALANCE_SHEETS,
        "Close status": CLOSE_STATUS,
    }


def after_posting(allocation: list[tuple[str, int]], reference: str) -> dict[str, list[Row]]:
    """The books a day later, once the Finance Admin posted WIRE-2901 as PMT-77."""
    sheets = deepcopy(full())
    sheets["Company"][0].update({"As of": date(2026, 11, 6), "Source reference": reference})
    sheets["Payments"] += _pay("PMT-77", "C1", date(2026, 11, 5), 9000, "WIRE-2901", allocation)
    applied = dict(allocation)
    for inv in sheets["Invoices"]:
        inv["Balance"] -= applied.get(inv["ID"], 0)
    return sheets


def broken() -> dict[str, list[Row]]:
    """Refused on import: an invoice of a customer who doesn't exist."""
    sheets = deepcopy(full())
    sheets["Company"][0]["Source reference"] = "Broken on purpose"
    sheets["Invoices"][0]["Customer ID"] = "C9"
    return sheets


def write(path: Path, sheets: dict[str, list[Row]]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        headers = list(dict.fromkeys(h for row in rows for h in row))
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(h) for h in headers])
        for column, header in zip(sheet.columns, headers, strict=False):
            width = max(len(str(c.value or "")) for c in column)
            sheet.column_dimensions[column[0].column_letter].width = min(
                max(width, len(header)) + 2, 48
            )
    workbook.save(path)
    print(f"Wrote {path}")


def _csv(path: Path, rows: Iterable[Row]) -> None:
    import csv

    rows = list(rows)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "reference",
                "payer",
                "date",
                "amount",
                "currency",
                "cleared",
                "proof_reference",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {path}")


def main(folder: Path = FOLDER) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / "service-pod.xlsx", full())
    write(
        folder / "service-pod-after-posting.xlsx",
        after_posting(
            [("I101", 6000), ("I102", 3000)], "Export after WIRE-2901 was posted as PMT-77"
        ),
    )
    write(
        folder / "service-pod-wrong-posting.xlsx",
        after_posting([("I101", 9000)], "Export after WIRE-2901 was posted to the wrong invoice"),
    )
    write(folder / "service-pod-broken.xlsx", broken())
    # A later statement: one new receipt (adds to a snapshot as a new snapshot)
    _csv(
        folder / "bank-statement-later.csv",
        [
            {
                "reference": "WIRE-3200",
                "payer": "Cobalt Systems",
                "date": "2026-11-06",
                "amount": "48500.00",
                "currency": "USD",
                "cleared": "yes",
                "proof_reference": "Statement 2026-11-06 line 4",
            },
        ],
    )


if __name__ == "__main__":
    main()
