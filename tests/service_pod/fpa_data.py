"""The deck's six-month FP&A dataset (Apr-Sep 2026, accrual, $), as a normalized export.

Monthly totals match the deck's table; the Aug -> Sep drivers match its screens: revenue
+60k (new enterprise invoice INV-411 +42k, expanded services INV-416 +26k, a declining base
-8k through a credit memo), cost of services +30k (subcontractors), operating expense +12k
(payroll +7k, cloud +3k, other +2k). Every GL line is the sum of its Posted transactions.
"""

import copy
from decimal import Decimal
from typing import Any

MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]

ACCOUNTS = [
    {"id": "A4000", "name": "Services revenue", "number": "4000", "classification": "Income"},
    {
        "id": "A5000",
        "name": "Subcontractors",
        "number": "5000",
        "classification": "CostOfGoodsSold",
    },
    {"id": "A6100", "name": "Operating payroll", "number": "6100", "classification": "Expense"},
    {"id": "A6200", "name": "Cloud and tools", "number": "6200", "classification": "Expense"},
    {"id": "A6300", "name": "Other operating costs", "number": "6300", "classification": "Expense"},
    {"id": "A7000", "name": "Interest income", "number": "7000", "classification": "OtherIncome"},
]

# Per month, in $000: (account, counterparty, type, document, amount)
_K = 1000
_ROWS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "2026-04": [
        ("A4000", "Harbor Distribution", "Invoice", "INV-301", 180),
        ("A4000", "Northwind Traders", "Invoice", "INV-302", 130),
        ("A4000", "Contoso Ltd", "Invoice", "INV-303", 110),
        ("A5000", "Delta Staffing", "Bill", "B-401", 150),
        ("A5000", "Apex Contractors", "Bill", "B-402", 102),
        ("A6100", "Payroll", "JournalEntry", "JE-501", 76),
        ("A6200", "CloudCo", "Expense", "EX-601", 16),
        ("A6300", "Office Supplies Co", "Expense", "EX-602", 13),
    ],
    "2026-05": [
        ("A4000", "Harbor Distribution", "Invoice", "INV-321", 185),
        ("A4000", "Northwind Traders", "Invoice", "INV-322", 140),
        ("A4000", "Contoso Ltd", "Invoice", "INV-323", 115),
        ("A5000", "Delta Staffing", "Bill", "B-421", 150),
        ("A5000", "Apex Contractors", "Bill", "B-422", 114),
        ("A6100", "Payroll", "JournalEntry", "JE-521", 78),
        ("A6200", "CloudCo", "Expense", "EX-621", 17),
        ("A6300", "Office Supplies Co", "Expense", "EX-622", 13),
    ],
    "2026-06": [
        ("A4000", "Harbor Distribution", "Invoice", "INV-341", 190),
        ("A4000", "Northwind Traders", "Invoice", "INV-342", 145),
        ("A4000", "Contoso Ltd", "Invoice", "INV-343", 125),
        ("A5000", "Delta Staffing", "Bill", "B-441", 150),
        ("A5000", "Apex Contractors", "Bill", "B-442", 126),
        ("A6100", "Payroll", "JournalEntry", "JE-541", 84),
        ("A6200", "CloudCo", "Expense", "EX-641", 18),
        ("A6300", "Office Supplies Co", "Expense", "EX-642", 14),
    ],
    "2026-07": [
        ("A4000", "Harbor Distribution", "Invoice", "INV-361", 195),
        ("A4000", "Northwind Traders", "Invoice", "INV-362", 140),
        ("A4000", "Contoso Ltd", "Invoice", "INV-363", 120),
        ("A5000", "Delta Staffing", "Bill", "B-461", 150),
        ("A5000", "Apex Contractors", "Bill", "B-462", 132),
        ("A6100", "Payroll", "JournalEntry", "JE-561", 87),
        ("A6200", "CloudCo", "Expense", "EX-661", 19),
        ("A6300", "Office Supplies Co", "Expense", "EX-662", 14),
    ],
    "2026-08": [
        ("A4000", "Harbor Distribution", "Invoice", "INV-381", 200),
        ("A4000", "Northwind Traders", "Invoice", "INV-382", 150),
        ("A4000", "Contoso Ltd", "Invoice", "INV-383", 130),
        ("A5000", "Delta Staffing", "Bill", "B-481", 150),
        ("A5000", "Apex Contractors", "Bill", "B-482", 138),
        ("A6100", "Payroll", "JournalEntry", "JE-581", 90),
        ("A6200", "CloudCo", "Expense", "EX-681", 20),
        ("A6300", "Office Supplies Co", "Expense", "EX-682", 15),
    ],
    "2026-09": [
        ("A4000", "Harbor Distribution", "Invoice", "INV-401", 200),
        ("A4000", "Northwind Traders", "Invoice", "INV-416", 176),
        ("A4000", "Contoso Ltd", "Invoice", "INV-403", 130),
        ("A4000", "Contoso Ltd", "CreditMemo", "CM-404", -8),
        ("A4000", "Fabrikam Enterprise", "Invoice", "INV-411", 42),
        ("A5000", "Delta Staffing", "Bill", "B-491", 150),
        ("A5000", "Apex Contractors", "Bill", "B-492", 168),
        ("A6100", "Payroll", "JournalEntry", "JE-591", 97),
        ("A6200", "CloudCo", "Expense", "EX-691", 23),
        ("A6300", "Office Supplies Co", "Expense", "EX-692", 17),
    ],
}


def fpa_document(**changes: Any) -> dict[str, Any]:
    """The dataset as a snapshot JSON export (add or replace top-level fields)."""
    gl_lines: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    for month in MONTHS:
        by_account: dict[str, list[str]] = {}
        totals: dict[str, Decimal] = {}
        for i, (account, who, kind, ref, amount) in enumerate(_ROWS[month]):
            txn_id = f"T-{ref}"
            gl_id = f"GL-{account}-{month}"
            by_account.setdefault(account, []).append(txn_id)
            totals[account] = totals.get(account, Decimal(0)) + amount * _K
            transactions.append(
                {
                    "id": txn_id,
                    "date": f"{month}-{10 + i:02d}",
                    "period": month,
                    "type": kind,
                    "counterparty": who,
                    "account_id": account,
                    "amount": str(amount * _K),
                    "status": "Posted",
                    "gl_line_id": gl_id,
                    "document_ref": ref,
                }
            )
        # Interest income: non-operating, disclosed but never counted as revenue
        by_account["A7000"] = [f"T-INT-{month}"]
        totals["A7000"] = Decimal(500)
        transactions.append(
            {
                "id": f"T-INT-{month}",
                "date": f"{month}-28",
                "period": month,
                "type": "Deposit",
                "counterparty": "First Bank",
                "account_id": "A7000",
                "amount": "500",
                "status": "Posted",
                "gl_line_id": f"GL-A7000-{month}",
                "document_ref": f"INT-{month}",
            }
        )
        for account, ids in by_account.items():
            gl_lines.append(
                {
                    "id": f"GL-{account}-{month}",
                    "account_id": account,
                    "period": month,
                    "amount": str(totals[account]),
                    "report_id": f"PL-{month}",
                    "transaction_ids": ids,
                }
            )
    # A draft bill: never a driver (Posted only), disclosed in the caveats
    transactions.append(
        {
            "id": "T-B-499",
            "date": "2026-09-29",
            "period": "2026-09",
            "type": "Bill",
            "counterparty": "Apex Contractors",
            "account_id": "A5000",
            "amount": "9000",
            "status": "Draft",
            "document_ref": "B-499",
        }
    )
    doc: dict[str, Any] = {
        "provenance": "QUICKBOOKS_READONLY_EXPORT",
        "company_id": "QB-ESOL-1",
        "company_name": "E-Solutions Inc",
        "entity": "US01",
        "currency": "USD",
        "basis": "Accrual",
        "as_of": "2026-10-05",
        "source_reference": "FP&A deck dataset",
        "accounts": copy.deepcopy(ACCOUNTS),
        "gl_lines": gl_lines,
        "transactions": transactions,
    }
    doc.update(changes)
    return doc
