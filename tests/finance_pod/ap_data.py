"""A small Procure-to-Pay snapshot for the AP-1 tests (fictional, like the ERPNext demo seed):
one department and lab, two grants, a contract vendor, a vendor on hold, budgets and an open
PO already committing part of one."""

import copy
from decimal import Decimal
from typing import Any

CC = "Gemology Research - GIAD"
LAB = "Carlsbad Lab"
GRANT = "PROJ-0001"
OLD_GRANT = "PROJ-0003"
EXPENSE = "Lab Consumables - GIAD"

AP_SNAPSHOT: dict[str, Any] = {
    "provenance": "SYNTHETIC_DEMO",
    "company_id": "erp.example.test:GIA Demo Labs",
    "company_name": "GIA Demo Labs",
    "entity": "US01",
    "currency": "USD",
    "basis": "Accrual",
    "as_of": "2026-11-03",
    "source_reference": "test ERPNext read",
    "accounts": [
        {"id": EXPENSE, "name": "Lab Consumables", "classification": "Expense"},
        {"id": "Lab Equipment - GIAD", "name": "Lab Equipment", "classification": "Expense"},
    ],
    "vendors": [
        {
            "id": "LabChem Supply Co",
            "name": "LabChem Supply Co",
            "status": "Active",
            "email": "orders@labchem.example.com",
        },
        {
            "id": "GemTech Instruments",
            "name": "GemTech Instruments",
            "status": "Active",
            "email": "sales@gemtech.example.com",
        },
        {
            "id": "Spectra Analytical",
            "name": "Spectra Analytical",
            "status": "Active",
            "email": "quotes@spectra.example.com",
        },
        {
            "id": "Kestrel Analytical",
            "name": "Kestrel Analytical",
            "status": "On hold",
            "email": "finance@kestrel.example.com",
        },
    ],
    "items": [
        {
            "code": "LC-PASTE",
            "name": "Diamond polishing paste",
            "group": "Lab Consumables",
            "stock_item": True,
            "expense_account_id": EXPENSE,
        },
        {
            "code": "LC-GLOVES",
            "name": "Nitrile gloves",
            "group": "Lab Consumables",
            "stock_item": True,
            "expense_account_id": EXPENSE,
        },
        {
            "code": "LE-UVVIS",
            "name": "UV-Vis-NIR spectrometer",
            "group": "Lab Equipment",
            "stock_item": True,
            "expense_account_id": "Lab Equipment - GIAD",
        },
    ],
    "item_prices": [
        {"item_code": "LC-PASTE", "rate": "42", "currency": "USD"},
        {
            "item_code": "LC-PASTE",
            "vendor_id": "LabChem Supply Co",
            "rate": "38",
            "currency": "USD",
        },
        {"item_code": "LC-GLOVES", "rate": "14.5", "currency": "USD"},
        {
            "item_code": "LC-GLOVES",
            "vendor_id": "Kestrel Analytical",
            "rate": "11",
            "currency": "USD",
        },
        {"item_code": "LE-UVVIS", "rate": "48000", "currency": "USD"},
    ],
    "vendor_contracts": [],
    "cost_centres": [{"id": CC, "name": "Gemology Research"}],
    "labs": [{"id": LAB, "name": LAB}],
    "grants": [
        {
            "id": GRANT,
            "name": "GR-2026-01 Diamond origin research",
            "start_date": "2026-01-01",
            "end_date": "2027-12-31",
            "restricted": True,
            "allowed_item_groups": ["Lab Consumables", "Lab Equipment"],
            "status": "Open",
        },
        {
            "id": OLD_GRANT,
            "name": "GR-2025-07 Synthetic detection study",
            "start_date": "2025-07-01",
            "end_date": "2026-06-30",
            "restricted": True,
            "allowed_item_groups": ["Lab Equipment"],
            "status": "Open",
        },
    ],
    "budgets": [
        {
            "id": "B-1",
            "against": "cost_centre",
            "target_id": CC,
            "account_id": EXPENSE,
            "fiscal_year": "2026",
            "amount": "5000",
        },
        {
            "id": "B-2",
            "against": "cost_centre",
            "target_id": CC,
            "account_id": "Lab Equipment - GIAD",
            "fiscal_year": "2026",
            "amount": "150000",
        },
        {
            "id": "B-3",
            "against": "grant",
            "target_id": GRANT,
            "account_id": EXPENSE,
            "fiscal_year": "2026",
            "amount": "3000",
        },
    ],
    "budget_actuals": [
        {
            "against": "cost_centre",
            "target_id": CC,
            "account_id": EXPENSE,
            "fiscal_year": "2026",
            "amount": "1200",
        },
    ],
    "purchase_requests": [
        {
            "id": "MAT-MR-1",
            "title": "UV-Vis spectrometer",
            "date": "2026-10-20",
            "status": "Pending",
            "doc_status": "Submitted",
            "lines": [
                {
                    "id": "mri-1",
                    "item_code": "LE-UVVIS",
                    "qty": "1",
                    "rate": "48000",
                    "cost_centre_id": CC,
                    "lab_id": LAB,
                    "grant_id": GRANT,
                    "account_id": "Lab Equipment - GIAD",
                }
            ],
        },
    ],
    "supplier_quotations": [
        {
            "id": "SQ-1",
            "vendor_id": "GemTech Instruments",
            "date": "2026-10-27",
            "status": "Submitted",
            "doc_status": "Submitted",
            "total": "47200",
            "lines": [
                {
                    "item_code": "LE-UVVIS",
                    "qty": "1",
                    "rate": "47200",
                    "lead_time_days": 45,
                    "request_id": "MAT-MR-1",
                    "request_line_id": "mri-1",
                }
            ],
        },
        {
            "id": "SQ-2",
            "vendor_id": "Spectra Analytical",
            "date": "2026-10-27",
            "status": "Submitted",
            "doc_status": "Submitted",
            "total": "45900",
            "lines": [
                {
                    "item_code": "LE-UVVIS",
                    "qty": "1",
                    "rate": "45900",
                    "lead_time_days": 70,
                    "request_id": "MAT-MR-1",
                    "request_line_id": "mri-1",
                }
            ],
        },
    ],
    "purchase_orders": [
        {
            "id": "PO-OLD",
            "vendor_id": "LabChem Supply Co",
            "date": "2026-09-01",
            "status": "To Receive and Bill",
            "doc_status": "Submitted",
            "total": "800",
            "lines": [
                {
                    "id": "pol-1",
                    "item_code": "LC-GLOVES",
                    "qty": "50",
                    "rate": "16",
                    "amount": "800",
                    "billed_amount": "0",
                    "cost_centre_id": CC,
                    "lab_id": LAB,
                    "account_id": EXPENSE,
                }
            ],
        },
    ],
}


def ap_payload(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(AP_SNAPSHOT)
    data.update(changes)
    return data


# A text W-9 and bank letter, as a vendor would upload them
W9 = (
    "Form W-9 Request for Taxpayer Identification Number and Certification\n"
    "Name (as shown on your income tax return): Nova Gem Tools LLC\n"
    "Employer identification number: 84-1234567\n"
)
BANK_LETTER = (
    "First Coastal Bank\n"
    "To whom it may concern: we confirm the account below.\n"
    "Account holder: Nova Gem Tools LLC\n"
    "Account number: 000123456789\n"
    "Routing number: 021000021\n"
)
SDN_CSV = (
    '36,"AEROCARIBBEAN AIRLINES",-0- ,"CUBA",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0-\n'
    '7157,"NOVA GEM TRADING",-0- ,"SDGT",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0-\n'
)


def _po(po_id: str, vendor: str, item: str, qty: str, rate: str) -> dict[str, Any]:
    amount = str(Decimal(qty) * Decimal(rate))
    return {
        "id": po_id,
        "vendor_id": vendor,
        "date": "2026-10-01",
        "status": "To Receive and Bill",
        "doc_status": "Submitted",
        "total": amount,
        "lines": [
            {
                "id": f"{po_id}-l1",
                "item_code": item,
                "qty": qty,
                "rate": rate,
                "amount": amount,
                "cost_centre_id": CC,
                "lab_id": LAB,
                "account_id": EXPENSE,
            }
        ],
    }


def _receipt(pr_id: str, po_id: str, vendor: str, item: str, qty: str, rate: str) -> dict[str, Any]:
    return {
        "id": pr_id,
        "vendor_id": vendor,
        "date": "2026-10-05",
        "status": "To Bill",
        "doc_status": "Submitted",
        "lines": [
            {
                "id": f"{pr_id}-l1",
                "item_code": item,
                "qty": qty,
                "rate": rate,
                "order_id": po_id,
                "order_line_id": f"{po_id}-l1",
            }
        ],
    }


def _bill(
    bill_id: str,
    number: str,
    vendor: str,
    item: str,
    qty: str,
    rate: str,
    po_id: str | None = None,
    status: str = "Draft",
    **extra: Any,
) -> dict[str, Any]:
    amount = str(Decimal(qty) * Decimal(rate))
    line: dict[str, Any] = {
        "item_code": item,
        "qty": qty,
        "rate": rate,
        "amount": amount,
        "cost_centre_id": CC,
        "account_id": EXPENSE,
    }
    if po_id:
        line |= {"order_id": po_id, "order_line_id": f"{po_id}-l1"}
    return {
        "id": bill_id,
        "vendor_id": vendor,
        "bill_number": number,
        "bill_date": "2026-10-10",
        "posting_date": "2026-10-10",
        "status": status,
        "doc_status": "Submitted" if status != "Draft" else "Draft",
        "total": amount,
        "outstanding": amount,
        "lines": [line],
        **extra,
    }


LC, GT = "LabChem Supply Co", "GemTech Instruments"
AP3_ORDERS = [
    _po("PO-OK", LC, "LC-PASTE", "10", "38"),  # received in full, billed at its price
    _po("PO-PRICE", LC, "LC-PASTE", "50", "12"),  # billed 9% above its price
    _po("PO-QTY", GT, "LC-GLOVES", "20", "14"),  # 10 received, 20 billed
    _po("PO-NONE", GT, "LC-GLOVES", "5", "14"),  # nothing received yet
    _po("PO-POSTED", LC, "LC-GLOVES", "60", "12.90"),
]
AP3_RECEIPTS = [
    _receipt("PR-OK", "PO-OK", LC, "LC-PASTE", "10", "38"),
    _receipt("PR-PRICE", "PO-PRICE", LC, "LC-PASTE", "50", "12"),
    _receipt("PR-QTY", "PO-QTY", GT, "LC-GLOVES", "10", "14"),
    _receipt("PR-POSTED", "PO-POSTED", LC, "LC-GLOVES", "60", "12.90"),
]
AP3_BILLS = [
    _bill("BILL-OK", "LC-5001", LC, "LC-PASTE", "10", "38.50", "PO-OK"),  # +1.3%: in tolerance
    _bill("BILL-PRICE", "LC-5002", LC, "LC-PASTE", "50", "13.10", "PO-PRICE"),
    _bill("BILL-QTY", "GT-901", GT, "LC-GLOVES", "20", "14", "PO-QTY"),
    _bill("BILL-NONE", "GT-902", GT, "LC-GLOVES", "5", "14", "PO-NONE"),
    _bill(
        "BILL-POSTED", "LC-INV-4502", LC, "LC-GLOVES", "60", "12.90", "PO-POSTED", status="Unpaid"
    ),
    _bill("BILL-DUP", "LC INV 4502", LC, "LC-GLOVES", "60", "12.90"),  # the same bill again
    _bill("BILL-NOPO", "CR-1101", GT, "LC-GLOVES", "3", "14"),
]


def ap3_payload(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "purchase_orders": [*AP_SNAPSHOT["purchase_orders"], *AP3_ORDERS],
        "purchase_receipts": AP3_RECEIPTS,
        "bills": AP3_BILLS,
    }
    return ap_payload(**(base | changes))


# --- AP-6: October 2026 closed on a snapshot of 3 November ---------------------------------
SERVICE = "SVC-MAINT"
ACCRUED = "Accrued Expenses - GIAD"
CREDITORS = "Creditors - GIAD"
SRBNB = "Stock Received But Not Billed - GIAD"
AP6_ORDERS = [
    _po("PO-BILLED", LC, "LC-PASTE", "20", "38"),  # received and billed (760 owed)
    _po("PO-STOCK", LC, "LC-GLOVES", "50", "12"),  # received, not billed: in SRBNB (600)
    _po("PO-SVC", GT, SERVICE, "1", "900"),  # a service done, not billed: to accrue
]
AP6_RECEIPTS = [
    _receipt("PR-BILLED", "PO-BILLED", LC, "LC-PASTE", "20", "38"),
    _receipt("PR-STOCK", "PO-STOCK", LC, "LC-GLOVES", "50", "12"),
    _receipt("PR-SVC", "PO-SVC", GT, SERVICE, "1", "900"),
]
AP6_BILLS = [
    _bill("BILL-BILLED", "LC-5001", LC, "LC-PASTE", "20", "38", "PO-BILLED", status="Unpaid"),
    _bill("BILL-GT", "GT-777", GT, "LC-GLOVES", "3", "14", status="Unpaid"),  # 42, no PO
]
# The ledger: both invoices (802), less a 100 rebate journalled to LabChem's account
AP6_LEDGER = {
    "ledger_balances": [
        {"account_id": CREDITORS, "kind": "payable", "as_of": "2026-11-03", "balance": "702"},
        {"account_id": SRBNB, "kind": "received_not_billed", "as_of": "2026-11-03",
         "balance": "600"},
        {"account_id": ACCRUED, "kind": "accrued", "as_of": "2026-11-03", "balance": "0"},
    ],
    "ledger_entries": [
        {"id": "GLE-1", "account_id": CREDITORS, "kind": "payable", "posting_date": "2026-10-10",
         "amount": "760", "voucher_type": "Purchase Invoice", "voucher_id": "BILL-BILLED",
         "party": LC},
        {"id": "GLE-2", "account_id": CREDITORS, "kind": "payable", "posting_date": "2026-10-10",
         "amount": "42", "voucher_type": "Purchase Invoice", "voucher_id": "BILL-GT",
         "party": GT},
        {"id": "GLE-3", "account_id": CREDITORS, "kind": "payable", "posting_date": "2026-10-20",
         "amount": "-100", "voucher_type": "Journal Entry", "voucher_id": "JE-REBATE",
         "party": LC},
    ],
    "journal_entries": [],
}  # fmt: skip
STATEMENT = (
    "LabChem Supply Co\n"
    "Statement of account, October 2026\n"
    "Date        Reference   Amount\n"
    "2026-10-10  LC-5001     760.00\n"
    "2026-10-28  LC-5099      55.00\n"
    "Closing balance         815.00\n"
)


def ap6_payload(**changes: Any) -> dict[str, Any]:
    items = [
        *AP_SNAPSHOT["items"],
        {"code": SERVICE, "name": "Instrument maintenance", "group": "Services",
         "stock_item": False, "expense_account_id": "Lab Equipment - GIAD"},
    ]  # fmt: skip
    base: dict[str, Any] = {
        "items": items,
        "purchase_orders": AP6_ORDERS,
        "purchase_receipts": AP6_RECEIPTS,
        "bills": AP6_BILLS,
        **AP6_LEDGER,
    }
    return ap_payload(**(base | changes))
