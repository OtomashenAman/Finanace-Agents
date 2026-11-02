"""A stand-in ERPNext site (httpx MockTransport): just enough of the Frappe REST API for the
connector, the importer and the app's postings. Figures are fictional test fixtures."""

import copy
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

import httpx

KEY, SECRET = "test-key", "test-secret"
COMPANY = "GIA Demo Labs"
CC = "Gemology Research - GIAD"
GRANT = "PROJ-0001"


def _line(name: str, code: str, qty: float, rate: float, **links: Any) -> dict[str, Any]:
    return {"name": name, "item_code": code, "qty": qty, "rate": rate, "amount": qty * rate,
            "cost_center": CC, "lab": "Carlsbad Lab", "project": GRANT,
            "expense_account": "Lab Consumables - GIAD", **links}  # fmt: skip


def _docs() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "Company": {COMPANY: {"name": COMPANY, "default_currency": "USD"}},
        "Buying Settings": {"Buying Settings": {"buying_price_list": "Standard Buying"}},
        "Material Request": {
            "MR-1": {
                "name": "MR-1",
                "company": COMPANY,
                "docstatus": 1,
                "status": "Pending",
                "title": "Polishing paste",
                "transaction_date": "2026-10-20",
                "material_request_type": "Purchase",
                "items": [
                    _line("mri-1", "LC-PASTE", 40, 42, schedule_date="2026-11-01", ordered_qty=0)
                ],
            },
        },
        "Supplier Quotation": {
            "SQ-1": {
                "name": "SQ-1",
                "company": COMPANY,
                "docstatus": 1,
                "status": "Submitted",
                "supplier": "LabChem Supply Co",
                "transaction_date": "2026-10-22",
                "valid_till": "2026-12-31",
                "grand_total": 1520,
                "terms": "<p>Net 30</p>",
                "items": [
                    {
                        "name": "sqi-1",
                        "item_code": "LC-PASTE",
                        "qty": 40,
                        "rate": 38,
                        "lead_time_days": 5,
                        "material_request": "MR-1",
                        "material_request_item": "mri-1",
                    }
                ],
            },
        },
        "Purchase Order": {
            "PO-1": {
                "name": "PO-1",
                "company": COMPANY,
                "docstatus": 1,
                "supplier": "LabChem Supply Co",
                "transaction_date": "2026-09-15",
                "status": "To Receive and Bill",
                "grand_total": 760,
                "items": [
                    _line(
                        "poi-1",
                        "LC-GLOVES",
                        2,
                        380,
                        received_qty=1,
                        billed_amt=0,
                        schedule_date="2026-10-01",
                        # an old request, outside the read window
                        material_request="MR-OLD",
                        material_request_item="mri-old",
                    )
                ],
            },
        },
        "Purchase Receipt": {
            "PR-1": {
                "name": "PR-1",
                "company": COMPANY,
                "docstatus": 1,
                "supplier": "LabChem Supply Co",
                "posting_date": "2026-10-02",
                "status": "To Bill",
                "items": [
                    {
                        "name": "pri-1",
                        "item_code": "LC-GLOVES",
                        "qty": 1,
                        "rejected_qty": 0,
                        "rate": 380,
                        "purchase_order": "PO-1",
                        "purchase_order_item": "poi-1",
                    }
                ],
            },
        },
        "Purchase Invoice": {
            "PI-1": {
                "name": "PI-1",
                "company": COMPANY,
                "docstatus": 0,
                "supplier": "LabChem Supply Co",
                "bill_no": "LC-77",
                "bill_date": "2026-10-05",
                "posting_date": "2026-10-05",
                "due_date": "2026-11-04",
                "status": "Draft",
                "grand_total": 760,
                "outstanding_amount": 760,
                "items": [
                    _line(
                        "pii-1",
                        "LC-GLOVES",
                        2,
                        380,
                        purchase_order="PO-1",
                        po_detail="poi-1",
                        purchase_receipt="PR-1",
                        pr_detail="pri-1",
                    )
                ],
            },
        },
        "Supplier": {},  # filled by _rows below; posted suppliers land here too
    }


ROWS: dict[str, list[dict[str, Any]]] = {
    "Supplier": [
        {"name": "LabChem Supply Co", "supplier_name": "LabChem Supply Co",
         "supplier_group": "Lab Suppliers", "tax_id": "84-1234567", "disabled": 0, "on_hold": 0},
        {"name": "Shadow Trading LLC", "supplier_name": "Shadow Trading LLC",
         "supplier_group": "General", "tax_id": None, "disabled": 1, "on_hold": 0},
    ],
    "Contact": [
        {"email_id": "orders@labchem.example.com", "is_primary_contact": 1,
         "link_name": "LabChem Supply Co"},
        {"email_id": "not-an-email", "is_primary_contact": 1, "link_name": "Shadow Trading LLC"},
    ],
    "Bank Account": [],
    "Item": [
        {"item_code": "LC-PASTE", "item_name": "Polishing paste", "item_group": "Lab Consumables",
         "is_stock_item": 1, "expense_account": "Lab Consumables - GIAD"},
        {"item_code": "LC-GLOVES", "item_name": "Gloves", "item_group": "Lab Consumables",
         "is_stock_item": 1, "expense_account": "Lab Consumables - GIAD"},
    ],
    "Item Price": [
        {"item_code": "LC-PASTE", "supplier": None, "price_list_rate": 42, "currency": "USD",
         "buying": 1, "price_list": "Standard Buying"},
        {"item_code": "LC-PASTE", "supplier": "LabChem Supply Co", "price_list_rate": 38,
         "currency": "USD", "buying": 1, "price_list": "Standard Buying"},
        {"item_code": "LC-PASTE", "supplier": None, "price_list_rate": 55, "currency": "USD",
         "buying": 0, "price_list": "Standard Selling"},  # a selling price: not read
    ],
    "Contract": [
        {"name": "CT-1", "party_name": "LabChem Supply Co", "start_date": "2026-01-01",
         "end_date": "2026-12-31", "contract_terms": "<b>Framework</b> agreement",
         "status": "Active", "party_type": "Supplier", "docstatus": 1},
    ],
    "Cost Center": [{"name": CC, "cost_center_name": "Gemology Research"}],
    "Accounting Dimension": [{"fieldname": "lab", "document_type": "Branch", "disabled": 0}],
    "Branch": [{"name": "Carlsbad Lab"}],
    "Project": [
        {"name": GRANT, "project_name": "GR-2026-01 Diamond origin research",
         "grant_funder": "NSF", "expected_start_date": "2026-01-01",
         "expected_end_date": "2027-12-31", "grant_restricted": 1,
         "grant_allowed_item_groups": "Lab Consumables, Lab Equipment", "status": "Open"},
    ],
    "Budget": [
        {"name": "BUDGET-1", "budget_against": "Cost Center", "cost_center": CC, "project": None,
         "account": "Lab Consumables - GIAD", "from_fiscal_year": "2026",
         "to_fiscal_year": "2026", "budget_amount": 60000, "docstatus": 1},
    ],
    "Fiscal Year": [
        {"name": "2026", "year_start_date": "2026-01-01", "year_end_date": "2026-12-31"},
    ],
    "GL Entry": [
        {"account": "Lab Consumables - GIAD", "cost_center": CC, "project": None,
         "debit": 1200, "credit": 0, "posting_date": "2026-06-30", "is_cancelled": 0},
        {"account": "Lab Consumables - GIAD", "cost_center": CC, "project": None,
         "debit": 999, "credit": 0, "posting_date": "2026-07-01", "is_cancelled": 1},
    ],
    "Account": [
        {"name": "Lab Consumables - GIAD", "account_name": "Lab Consumables",
         "account_number": "", "root_type": "Expense", "account_type": "Expense Account"},
        {"name": "Creditors - GIAD", "account_name": "Creditors", "account_number": "",
         "root_type": "Liability", "account_type": "Payable"},
    ],
}  # fmt: skip


def _field(name: str) -> str:
    return name.split(".")[-1].strip("`")


class FakeErpNext:
    def __init__(self) -> None:
        self.docs = _docs()
        self.rows = copy.deepcopy(ROWS)
        self.inserted: list[dict[str, Any]] = []
        self.submitted: list[tuple[str, str]] = []
        self.fail_after_insert = False  # the insert happens, the answer is lost
        self.key = KEY

    def _auth(self, request: httpx.Request) -> bool:
        return request.headers.get("Authorization") == f"token {self.key}:{SECRET}"

    def _matches(self, row: dict[str, Any], filters: list[list[Any]]) -> bool:
        for f in filters:
            if len(f) == 4:  # a child-table filter: the fake's rows are already flat
                continue
            field, op, value = f
            if field in ("company", "is_group") and field not in row:  # left out of fixtures
                continue
            have = row.get(field)
            if op == "=" and have != value:
                return False
            if op == "<" and not (have is not None and have < value):
                return False
            if op == ">=" and not (have is not None and str(have) >= str(value)):
                return False
            if op == "in" and have not in value:
                return False
        return True

    def _list(self, doctype: str, params: httpx.QueryParams) -> list[dict[str, Any]]:
        fields = [_field(f) for f in json.loads(params.get("fields", '["name"]'))]
        filters = json.loads(params.get("filters", "[]"))
        if doctype in self.rows and doctype != "Supplier":
            source = self.rows[doctype]
        elif doctype == "Supplier":
            source = self.rows["Supplier"] + list(self.docs["Supplier"].values())
        else:
            source = list(self.docs.get(doctype, {}).values())
        found = [r for r in source if self._matches(r, filters)]
        if fields == ["*"]:
            return copy.deepcopy(found)
        return [{f: r.get(f) for f in fields} for r in found]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self._auth(request):
            return httpx.Response(401, json={"exc_type": "AuthenticationError"})
        path = unquote(request.url.path)
        if path == "/api/method/frappe.auth.get_logged_user":
            return httpx.Response(200, json={"message": "finance-acc@example.com"})
        parts = path.removeprefix("/api/resource/").split("/")
        doctype = parts[0]
        if request.method == "GET" and len(parts) == 1:
            return httpx.Response(200, json={"data": self._list(doctype, request.url.params)})
        if request.method == "GET":
            doc = self.docs.get(doctype, {}).get(parts[1])
            if doc is None:
                return httpx.Response(404, json={"exc_type": "DoesNotExistError"})
            return httpx.Response(200, json={"data": copy.deepcopy(doc)})
        if request.method == "POST":
            body = json.loads(request.content)
            name = (
                body.get("supplier_name") or f"{doctype[:3].upper()}-NEW-{len(self.inserted) + 1}"
            )
            doc = {**body, "name": name, "docstatus": 0, "company": body.get("company", COMPANY)}
            self.docs.setdefault(doctype, {})[name] = doc
            self.inserted.append(doc)
            if self.fail_after_insert:
                self.fail_after_insert = False
                return httpx.Response(502, text="Bad gateway")
            return httpx.Response(200, json={"data": doc})
        if request.method == "PUT":
            doc = self.docs[doctype][parts[1]]
            doc.update(json.loads(request.content))
            self.submitted.append((doctype, parts[1]))
            return httpx.Response(200, json={"data": doc})
        return httpx.Response(405)


Transport = Callable[[httpx.Request], httpx.Response]
