"""Seed the local ERPNext (ops/erpnext) with a GIA-like demo company for the Finance POD.

    uv run poe erpnext-seed              # setup wizard, masters, transactions, API user
    uv run poe erpnext-seed --new-keys   # also issue a new API secret for the app
    uv run poe erpnext-seed --more       # a new batch of invoices to match, submissions to bill

`docker compose up` runs it by itself (the erpnext-seed service): it waits for a new site,
seeds it, and gives the API user the key/secret of ERPNEXT_API_KEY / ERPNEXT_API_SECRET, so
the app connects with no copy-pasting.

ERPNext v16's own demo data is only a few masters (3 suppliers, 10 items, no transactions),
so this builds what the AP agents need, every figure fictional and every email @example.com:

- Masters: company "GIA Demo Labs" (USD, fiscal year 2026); labs (Branch, used as the "Lab"
  accounting dimension); departments (cost centres); grants (Projects with funder, period,
  restricted fund and allowed item groups); expense accounts; items with standard and
  supplier contract prices; suppliers (approved, one blocked, one on hold, one without an
  email); a framework contract; budgets per department and grant (one nearly used up).
- AP-1: purchase requests (approved, draft, urgent, without a grant), and a high-value
  request with three supplier quotations waiting for the buyer.
- AP-3: purchase orders and receipts, and incoming supplier invoices (drafts) that match
  cleanly, carry a price variance, bill more than was received, have no receipt, duplicate a
  posted one, or have no PO at all.
- AP-6: goods received and not invoiced (in Stock Received But Not Billed), a service
  received and not invoiced (to accrue), a rebate journalled to a supplier's account (the AP
  subledger and ledger differ), posted invoices and a payment.
- AR (Order-to-Cash): lab services with selling prices, a client's own price and a trade
  discount; domestic and export (zero-rated) sales tax; clients with credit limits and terms
  (a key account, one deposit-only, one on hold, one without a contact); lab submissions as
  sales orders (custom "Report issued on" and "Fee estimate"; one with an added service, one
  still in the lab); posted invoices across the ageing buckets, a late payment and a partial
  one. GIA's lab system isn't connected: the sales order stands in for it.

Masters are get-or-create, so reruns are safe; transactions are created once (Notes named
"finance-acc-demo-seed" and "finance-acc-ar-seed" mark them). Talks to ERPNext's REST API only.
"""

import argparse
import json
import os
import sys
import time
from typing import Any
from urllib.parse import quote

import httpx

URL = os.environ.get("ERPNEXT_URL", "http://localhost:8090")
ADMIN_PASSWORD = os.environ.get("ERPNEXT_ADMIN_PASSWORD", "admin")
COMPANY, ABBR = "GIA Demo Labs", "GIAD"
FY = "2026"
STORES = f"Stores - {ABBR}"
MARKER = "finance-acc-demo-seed"
API_USER = "finance-acc@example.com"
# What the app reads (suppliers, prices, budgets, GL, the Lab dimension's doctype) and
# writes after approval (suppliers, POs, receipts, invoices, journals)
API_ROLES = (
    "Purchase Manager", "Purchase User", "Purchase Master Manager", "Accounts Manager",
    "Accounts User", "Stock Manager", "Stock User", "Item Manager", "Projects Manager",
    "Projects User", "HR User", "Sales Manager", "Sales User", "Sales Master Manager",
)  # fmt: skip


class ErpError(RuntimeError):
    pass


def _path(doctype: str, name: str) -> str:
    return f"/api/resource/{doctype}/{quote(name, safe='')}"


class Erp:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=URL, timeout=300)

    def login(self, wait: int = 0) -> None:
        """Sign in as Administrator; `wait` seconds for a site still being created."""
        deadline = time.monotonic() + wait
        while True:
            try:
                r = self.http.post(
                    "/api/method/login", json={"usr": "Administrator", "pwd": ADMIN_PASSWORD}
                )
                if r.status_code == 200:
                    return
                problem = r.text[:200]
            except httpx.HTTPError as exc:
                problem = str(exc)
            if time.monotonic() >= deadline:
                raise ErpError(f"Can't sign in to ERPNext at {URL}: {problem}")
            print(f"Waiting for ERPNext at {URL} ({problem[:80]})...")
            time.sleep(15)

    def _check(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            try:
                body = r.json()
                detail = body.get("exception") or body.get("_server_messages") or body
            except ValueError:
                detail = r.text
            raise ErpError(f"{r.request.method} {r.request.url.path}: {str(detail)[:600]}")
        return r.json()

    def call(self, method: str, **kwargs: Any) -> Any:
        data = {k: v if isinstance(v, str) else json.dumps(v) for k, v in kwargs.items()}
        return self._check(self.http.post(f"/api/method/{method}", data=data)).get("message")

    def find(self, doctype: str, filters: dict[str, Any]) -> str | None:
        params = {"filters": json.dumps(filters), "fields": '["name"]', "limit_page_length": 1}
        rows = self._check(self.http.get(f"/api/resource/{doctype}", params=params))["data"]
        return rows[0]["name"] if rows else None

    def get(self, doctype: str, name: str) -> dict[str, Any]:
        doc: dict[str, Any] = self._check(self.http.get(_path(doctype, name)))["data"]
        return doc

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = self._check(
            self.http.post(f"/api/resource/{doc['doctype']}", json=doc)
        )["data"]
        return out

    def ensure(self, doc: dict[str, Any], key: dict[str, Any]) -> str:
        """The existing document matching `key`, or a new one."""
        found = self.find(doc["doctype"], key)
        return found if found else self.insert(doc)["name"]

    def submit(self, doctype: str, name: str) -> dict[str, Any]:
        out: dict[str, Any] = self._check(
            self.http.put(_path(doctype, name), json={"docstatus": 1})
        )["data"]
        return out

    def update(self, doctype: str, name: str, values: dict[str, Any]) -> None:
        self._check(self.http.put(_path(doctype, name), json=values))


# --- setup and masters ---------------------------------------------------------------------


def setup_company(erp: Erp) -> None:
    if erp.find("Company", {"name": COMPANY}):
        return
    print("Running the setup wizard (company GIA Demo Labs, USD, fiscal year 2026)...")
    erp.call(
        "frappe.desk.page.setup_wizard.setup_wizard.setup_complete",
        args={
            "language": "English", "country": "United States", "timezone": "America/Los_Angeles",
            "currency": "USD", "company_name": COMPANY, "company_abbr": ABBR,
            "chart_of_accounts": "Standard", "fy_start_date": "2026-01-01",
            "fy_end_date": "2026-12-31", "setup_demo": 0, "enable_telemetry": 0,
        },
    )  # fmt: skip


LABS = ("Carlsbad Lab", "New York Lab", "Mumbai Lab", "Antwerp Lab")
DEPARTMENTS = ("Gemology Research", "Grading Operations", "Education", "Facilities", "IT")
ACCOUNTS = ("Lab Consumables", "Lab Equipment", "IT Equipment", "Professional Services")
ITEM_GROUPS = ("Lab Consumables", "Lab Equipment", "IT Hardware", "Professional Services",
               "Office Supplies")  # fmt: skip

# code, name, group, stock item, standard buying rate, expense account
ITEMS = (
    ("LC-PASTE", "Diamond polishing paste 10g", "Lab Consumables", 1, 42.00, "Lab Consumables"),
    ("LC-RIFLUID", "Refractometer fluid RI 1.81", "Lab Consumables", 1, 118.00, "Lab Consumables"),
    ("LC-GLOVES", "Nitrile gloves (box of 100)", "Lab Consumables", 1, 14.50, "Lab Consumables"),
    ("LC-BAGS", "Gem sample bags (pack of 500)", "Lab Consumables", 1, 36.00, "Lab Consumables"),
    ("LC-LAMP", "Microscope halogen lamp", "Lab Consumables", 1, 12.00, "Lab Consumables"),
    ("LE-MICRO", "Gemological microscope 10-80x", "Lab Equipment", 1, 6500.00, "Lab Equipment"),
    ("LE-UVVIS", "UV-Vis-NIR spectrometer", "Lab Equipment", 1, 48000.00, "Lab Equipment"),
    ("LE-FTIR", "FTIR diamond accessory", "Lab Equipment", 1, 9800.00, "Lab Equipment"),
    ("IT-LAPTOP", "Laptop 14in (lab analyst)", "IT Hardware", 1, 1450.00, "IT Equipment"),
    ("IT-BARCODE", "Barcode label printer", "IT Hardware", 1, 640.00, "IT Equipment"),
    ("SV-CALIB", "Spectrometer calibration service", "Professional Services", 0, 2400.00,
     "Professional Services"),
    ("SV-MAINT", "Equipment preventive maintenance", "Professional Services", 0, 1800.00,
     "Professional Services"),
    ("OF-PAPER", "Printer paper A4 (case)", "Office Supplies", 1, 38.00, "Print and Stationery"),
)  # fmt: skip

# name, group, email (None: none on file), tax id, flags
SUPPLIERS = (
    ("LabChem Supply Co", "Lab Suppliers", "orders@labchem.example.com", "84-1234567", {}),
    ("GemTech Instruments", "Lab Suppliers", "sales@gemtech.example.com", "95-2345678", {}),
    ("Precision Optics Inc", "Lab Suppliers", "ar@precisionoptics.example.com", "33-3456789", {}),
    ("Spectra Analytical", "Lab Suppliers", "quotes@spectra.example.com", "47-4567890", {}),
    ("Pacific IT Solutions", "IT Vendors", "billing@pacificit.example.com", "26-5678901", {}),
    ("CalibrateRight Services", "Service Providers", "ops@calibrateright.example.com",
     "61-6789012", {}),
    ("Summit Office Supplies", "General Vendors", None, "52-7890123", {}),
    ("Shadow Trading LLC", "General Vendors", "info@shadowtrading.example.com", "00-0000000",
     {"disabled": 1}),
    ("Kestrel Analytical", "Lab Suppliers", "finance@kestrel.example.com", "73-8901234",
     {"on_hold": 1, "hold_type": "All"}),
)  # fmt: skip

# Contract prices (supplier-specific buying prices, below the standard rate)
CONTRACT_PRICES = (
    ("LabChem Supply Co", "LC-PASTE", 38.00),
    ("LabChem Supply Co", "LC-RIFLUID", 105.00),
    ("LabChem Supply Co", "LC-GLOVES", 12.90),
    ("LabChem Supply Co", "LC-BAGS", 32.00),
    ("Precision Optics Inc", "LC-LAMP", 12.00),
    ("GemTech Instruments", "LE-MICRO", 6500.00),
)

# project name, funder, start, end, restricted, allowed item groups
GRANTS = (
    ("GR-2026-01 Diamond origin research", "National Science Foundation", "2026-01-01",
     "2027-12-31", 1, "Lab Consumables, Lab Equipment"),
    ("GR-2026-02 Colored stone education", "GIA Endowment", "2026-01-01", "2026-12-31", 0, ""),
    ("GR-2025-07 Synthetic detection study", "Jewelers Vigilance Fund", "2025-07-01",
     "2026-06-30", 1, "Lab Consumables"),
    ("GR-2026-03 Pearl identification", "Private donor", "2026-03-01", "2026-12-31", 1,
     "Lab Consumables, Professional Services"),
)  # fmt: skip

# budget against, name, account, amount
BUDGETS = (
    ("Cost Center", "Gemology Research", "Lab Consumables", 60000),
    ("Cost Center", "Gemology Research", "Lab Equipment", 150000),
    ("Cost Center", "Grading Operations", "Lab Consumables", 40000),
    ("Cost Center", "IT", "IT Equipment", 25000),
    ("Cost Center", "Facilities", "Professional Services", 30000),
    ("Project", "GR-2026-01 Diamond origin research", "Lab Equipment", 120000),
    ("Project", "GR-2026-03 Pearl identification", "Lab Consumables", 5000),
)


def cc(department: str) -> str:
    return f"{department} - {ABBR}"


def acct(name: str) -> str:
    return f"{name} - {ABBR}"


def custom_field(erp: Erp, dt: str, fieldname: str, label: str, fieldtype: str, after: str) -> None:
    erp.ensure(
        {"doctype": "Custom Field", "dt": dt, "fieldname": fieldname, "label": label,
         "fieldtype": fieldtype, "insert_after": after,
         "read_only": 1 if fieldname in ("finance_acc_ref", "seed_ref") else 0,
         "hidden": 1 if fieldname == "seed_ref" else 0},
        {"dt": dt, "fieldname": fieldname},
    )  # fmt: skip


def wait_for_dimension(erp: Erp) -> None:
    """The Lab dimension's fields are added by a background job."""
    for _ in range(60):
        if erp.find("Custom Field", {"dt": "Purchase Order Item", "fieldname": "lab"}):
            return
        time.sleep(2)
    raise ErpError("The Lab accounting dimension wasn't added (is the queue worker running?).")


def masters(erp: Erp) -> dict[str, str]:
    print("Masters: labs, departments, grants, accounts, items, suppliers, budgets...")
    # Incoming invoices may differ from the PO (that's what AP-3 matching is for): ERPNext
    # must accept them as drafts instead of refusing a different rate outright
    erp.update("Buying Settings", "Buying Settings", {"maintain_same_rate": 0})
    for lab in LABS:
        erp.ensure({"doctype": "Branch", "branch": lab}, {"name": lab})
    erp.ensure(
        {"doctype": "Accounting Dimension", "document_type": "Branch", "label": "Lab",
         "dimension_defaults": [{"company": COMPANY}]},
        {"document_type": "Branch"},
    )  # fmt: skip
    wait_for_dimension(erp)

    for dep in DEPARTMENTS:
        erp.ensure(
            {"doctype": "Cost Center", "cost_center_name": dep, "company": COMPANY,
             "parent_cost_center": f"{COMPANY} - {ABBR}", "is_group": 0},
            {"name": cc(dep)},
        )  # fmt: skip

    custom_field(erp, "Project", "grant_funder", "Grant funder", "Data", "project_name")
    custom_field(erp, "Project", "grant_restricted", "Restricted fund", "Check", "grant_funder")
    custom_field(
        erp,
        "Project",
        "grant_allowed_item_groups",
        "Allowed item groups",
        "Small Text",
        "grant_restricted",
    )
    # Which seed step made a transaction, so a rerun after a failure doesn't repeat it
    for dt in ("Material Request", "Supplier Quotation", "Purchase Order", "Purchase Receipt",
               "Purchase Invoice", "Payment Entry", "Journal Entry", "Note"):  # fmt: skip
        custom_field(erp, dt, "seed_ref", "Demo seed reference", "Data", "naming_series")
    # Our reference on what the app posts, so a retried post finds the first one
    for dt in ("Supplier", "Purchase Order", "Purchase Receipt", "Purchase Invoice",
               "Journal Entry"):  # fmt: skip
        custom_field(erp, dt, "finance_acc_ref", "Finance ACC reference", "Data", "naming_series")

    grants = {}
    for name, funder, start, end, restricted, groups in GRANTS:
        grants[name] = erp.ensure(
            {"doctype": "Project", "project_name": name, "company": COMPANY, "status": "Open",
             "expected_start_date": start, "expected_end_date": end, "grant_funder": funder,
             "grant_restricted": restricted, "grant_allowed_item_groups": groups},
            {"project_name": name},
        )  # fmt: skip

    for name in ACCOUNTS:
        erp.ensure(
            {"doctype": "Account", "account_name": name, "company": COMPANY, "is_group": 0,
             "parent_account": acct("Indirect Expenses"), "account_type": "Expense Account"},
            {"name": acct(name)},
        )  # fmt: skip

    for group in ITEM_GROUPS:
        erp.ensure(
            {"doctype": "Item Group", "item_group_name": group,
             "parent_item_group": "All Item Groups"},
            {"name": group},
        )  # fmt: skip
    for code, name, group, stock, rate, account in ITEMS:
        erp.ensure(
            {"doctype": "Item", "item_code": code, "item_name": name, "item_group": group,
             "stock_uom": "Nos", "is_stock_item": stock, "is_purchase_item": 1,
             "is_sales_item": 0, "include_item_in_manufacturing": 0,
             "item_defaults": [{"company": COMPANY, "expense_account": acct(account),
                                "default_warehouse": STORES if stock else None}]},
            {"name": code},
        )  # fmt: skip
        erp.ensure(
            {"doctype": "Item Price", "item_code": code, "price_list": "Standard Buying",
             "price_list_rate": rate, "uom": "Nos"},
            {"item_code": code, "price_list": "Standard Buying", "supplier": ["is", "not set"]},
        )  # fmt: skip

    for group in {s[1] for s in SUPPLIERS}:
        erp.ensure(
            {"doctype": "Supplier Group", "supplier_group_name": group,
             "parent_supplier_group": "All Supplier Groups"},
            {"name": group},
        )  # fmt: skip
    for name, group, email, tax_id, flags in SUPPLIERS:
        erp.ensure(
            {"doctype": "Supplier", "supplier_name": name, "supplier_group": group,
             "tax_id": tax_id, "supplier_type": "Company", "country": "United States", **flags},
            {"name": name},
        )  # fmt: skip
        if email:
            erp.ensure(
                {"doctype": "Contact", "first_name": "Accounts", "last_name": name,
                 "email_ids": [{"email_id": email, "is_primary": 1}],
                 "links": [{"link_doctype": "Supplier", "link_name": name}],
                 "is_primary_contact": 1},
                {"email_id": email},
            )  # fmt: skip
    for supplier, item, rate in CONTRACT_PRICES:
        erp.ensure(
            {"doctype": "Item Price", "item_code": item, "price_list": "Standard Buying",
             "price_list_rate": rate, "uom": "Nos", "supplier": supplier},
            {"item_code": item, "price_list": "Standard Buying", "supplier": supplier},
        )  # fmt: skip
    erp.ensure(
        {"doctype": "Contract", "party_type": "Supplier", "party_name": "LabChem Supply Co",
         "start_date": "2026-01-01", "end_date": "2026-12-31",
         "contract_terms": "Framework agreement FA-2026-LC: lab consumables at the agreed "
                           "contract prices, delivery within 5 business days, net 30."},
        {"party_name": "LabChem Supply Co"},
    )  # fmt: skip

    for against, target, account, amount in BUDGETS:
        field = "cost_center" if against == "Cost Center" else "project"
        value = cc(target) if against == "Cost Center" else grants[target]
        if erp.find("Budget", {field: value, "account": acct(account), "docstatus": 1}):
            continue
        budget = erp.insert(
            {"doctype": "Budget", "budget_against": against, "company": COMPANY, field: value,
             "account": acct(account), "from_fiscal_year": FY, "to_fiscal_year": FY,
             "distribution_frequency": "Yearly", "budget_amount": amount,
             "distribute_equally": 1,
             "applicable_on_material_request": 1,
             "action_if_annual_budget_exceeded_on_mr": "Warn",
             "applicable_on_purchase_order": 1, "action_if_annual_budget_exceeded_on_po": "Warn",
             "applicable_on_booking_actual_expenses": 1,
             "action_if_annual_budget_exceeded": "Warn"}
        )  # fmt: skip
        erp.submit("Budget", budget["name"])
    return grants


# --- transactions --------------------------------------------------------------------------


def line(code: str, qty: float, rate: float, dept: str, lab: str, grant: str | None,
         date: str) -> dict[str, Any]:  # fmt: skip
    item = next(i for i in ITEMS if i[0] == code)
    return {
        "item_code": code, "qty": qty, "rate": rate, "schedule_date": date,
        "cost_center": cc(dept), "lab": lab, "project": grant,
        "expense_account": acct(item[5]), "warehouse": STORES if item[3] else None,
        "uom": "Nos", "conversion_factor": 1,
    }  # fmt: skip


def seeded(erp: Erp, doctype: str, ref: str) -> str | None:
    return erp.find(doctype, {"seed_ref": ref})


def request(
    erp: Erp, ref: str, title: str, date: str, lines: list[dict[str, Any]], submit: bool
) -> str:
    if found := seeded(erp, "Material Request", ref):
        return found
    doc = erp.insert(
        {"doctype": "Material Request", "material_request_type": "Purchase", "company": COMPANY,
         "transaction_date": date, "schedule_date": lines[0]["schedule_date"], "title": title,
         "set_warehouse": STORES, "items": lines, "seed_ref": ref}
    )  # fmt: skip
    if submit:
        erp.submit("Material Request", doc["name"])
    return str(doc["name"])


def order_from(
    erp: Erp, ref: str, mr: str, supplier: str, date: str, rates: dict[str, float]
) -> str:
    if found := seeded(erp, "Purchase Order", ref):
        return found
    po = erp.call(
        "erpnext.stock.doctype.material_request.material_request.make_purchase_order",
        source_name=mr,
    )
    needed_by = erp.get("Material Request", mr)["schedule_date"]
    po.update({"supplier": supplier, "transaction_date": date, "seed_ref": ref,
               "schedule_date": needed_by})  # fmt: skip
    for item in po["items"]:
        item["rate"] = rates.get(item["item_code"], item.get("rate"))
        item.setdefault("schedule_date", needed_by)
    name = erp.insert(po)["name"]
    erp.submit("Purchase Order", name)
    return str(name)


def order(erp: Erp, ref: str, supplier: str, date: str, lines: list[dict[str, Any]]) -> str:
    """A PO without a purchase request (as happens today for urgent buys)."""
    if found := seeded(erp, "Purchase Order", ref):
        return found
    doc = erp.insert(
        {"doctype": "Purchase Order", "supplier": supplier, "company": COMPANY,
         "transaction_date": date, "schedule_date": lines[0]["schedule_date"],
         "set_warehouse": STORES, "items": lines, "seed_ref": ref}
    )  # fmt: skip
    erp.submit("Purchase Order", doc["name"])
    return str(doc["name"])


def receive(erp: Erp, ref: str, po: str, date: str, qty: dict[str, float] | None = None) -> str:
    if found := seeded(erp, "Purchase Receipt", ref):
        return found
    pr = erp.call(
        "erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt",
        source_name=po,
    )
    pr.update({"posting_date": date, "set_posting_time": 1, "seed_ref": ref})
    for item in pr["items"]:
        if qty and item["item_code"] in qty:
            item["qty"] = item["received_qty"] = qty[item["item_code"]]
    name = erp.insert(pr)["name"]
    erp.submit("Purchase Receipt", name)
    return str(name)


def invoice(
    erp: Erp,
    ref: str,
    source: tuple[str, str],
    bill_no: str,
    date: str,
    *,
    rates: dict[str, float] | None = None,
    submit: bool = False,
) -> str:
    """A supplier invoice mapped from its PO or receipt; a draft is one that has come in
    and waits for matching (AP-3), a submitted one is posted."""
    if found := seeded(erp, "Purchase Invoice", ref):
        return found
    method = {
        "Purchase Order": "erpnext.buying.doctype.purchase_order.purchase_order",
        "Purchase Receipt": "erpnext.stock.doctype.purchase_receipt.purchase_receipt",
    }[source[0]] + ".make_purchase_invoice"
    pi = erp.call(method, source_name=source[1])
    pi.update({"bill_no": bill_no, "bill_date": date, "posting_date": date,
               "set_posting_time": 1, "seed_ref": ref})  # fmt: skip
    for item in pi["items"]:
        if rates and item["item_code"] in rates:
            item["rate"] = rates[item["item_code"]]
    name = erp.insert(pi)["name"]
    if submit:
        erp.submit("Purchase Invoice", name)
    return str(name)


def resend(erp: Erp, ref: str, original: str, date: str) -> None:
    """The same supplier bill arriving again by email, unlinked to the PO or receipt."""
    if seeded(erp, "Purchase Invoice", ref):
        return
    first = erp.get("Purchase Invoice", original)
    keep = ("item_code", "qty", "rate", "uom", "conversion_factor", "cost_center", "lab",
            "project", "expense_account")  # fmt: skip
    erp.insert(
        {"doctype": "Purchase Invoice", "supplier": first["supplier"], "company": COMPANY,
         "seed_ref": ref, "bill_no": first["bill_no"], "bill_date": first["bill_date"],
         "posting_date": date, "set_posting_time": 1,
         "items": [{k: i.get(k) for k in keep} for i in first["items"]]}
    )  # fmt: skip


def quotation(erp: Erp, ref: str, mr: str, supplier: str, date: str, rate: float, days: int) -> str:
    if found := seeded(erp, "Supplier Quotation", ref):
        return found
    request_doc = erp.get("Material Request", mr)
    items = [
        {"item_code": i["item_code"], "qty": i["qty"], "rate": rate, "uom": "Nos",
         "conversion_factor": 1, "material_request": mr, "material_request_item": i["name"],
         "lead_time_days": days, "warehouse": STORES}
        for i in request_doc["items"]
    ]  # fmt: skip
    doc = erp.insert(
        {"doctype": "Supplier Quotation", "supplier": supplier, "company": COMPANY,
         "transaction_date": date, "valid_till": "2026-12-31", "currency": "USD",
         "conversion_rate": 1, "items": items, "seed_ref": ref,
         "terms": f"Delivery {days} days after PO; installation and training included."}
    )  # fmt: skip
    erp.submit("Supplier Quotation", doc["name"])
    return str(doc["name"])


def pay(erp: Erp, ref: str, pi: str, date: str) -> None:
    if seeded(erp, "Payment Entry", ref):
        return
    pe = erp.call(
        "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
        dt="Purchase Invoice", dn=pi,
    )  # fmt: skip
    pe.update({"posting_date": date, "reference_no": f"ACH-{pi[-5:]}", "reference_date": date,
               "seed_ref": ref})  # fmt: skip
    name = erp.insert(pe)["name"]
    erp.submit("Payment Entry", name)


def transactions(erp: Erp, grants: dict[str, str]) -> None:
    if erp.find("Note", {"title": MARKER}) and seeded(erp, "Journal Entry", "JE-REBATE"):
        print("Transactions already seeded (Note finance-acc-demo-seed): skipped.")
        return
    print("Transactions: purchase requests, quotations, POs, receipts, invoices, payment...")
    g1 = grants["GR-2026-01 Diamond origin research"]
    g3 = grants["GR-2025-07 Synthetic detection study"]
    g4 = grants["GR-2026-03 Pearl identification"]

    # AP-1: purchase requests
    research = ("Gemology Research", "Carlsbad Lab")
    pearl = ("Grading Operations", "Mumbai Lab")
    mr_happy = request(
        erp, "MR-HAPPY", "Polishing paste and RI fluid for Carlsbad research", "2026-08-03",
        [line("LC-PASTE", 40, 42, *research, g1, "2026-08-14"),
         line("LC-RIFLUID", 10, 118, *research, g1, "2026-08-14")],
        submit=True,
    )  # fmt: skip
    mr_spectro = request(
        erp, "MR-SPECTRO", "UV-Vis-NIR spectrometer for diamond origin work", "2026-10-20",
        [line("LE-UVVIS", 1, 48000, *research, g1, "2026-12-15")],
        submit=True,
    )  # fmt: skip
    request(
        erp, "MR-LAPTOPS", "Two laptops for new NY analysts", "2026-10-29",
        [line("IT-LAPTOP", 2, 1450, "IT", "New York Lab", None, "2026-11-20")],
        submit=False,
    )  # fmt: skip
    request(
        erp, "MR-EXPIRED-GRANT", "Gloves charged to a grant that ended", "2026-10-30",
        [line("LC-GLOVES", 30, 14.5, *pearl, g3, "2026-11-10")],
        submit=False,
    )  # fmt: skip
    request(
        erp, "MR-PEARL", "Sample bags for pearl identification", "2026-10-31",
        [line("LC-BAGS", 40, 36, *pearl, g4, "2026-11-12")],
        submit=True,
    )  # fmt: skip
    for supplier, rate, days in (
        ("GemTech Instruments", 47200, 45),
        ("Spectra Analytical", 45900, 70),
        ("Precision Optics Inc", 49500, 30),
    ):
        quotation(erp, f"SQ-{supplier[:8]}", mr_spectro, supplier, "2026-10-27", rate, days)

    # AP-3 / AP-6: orders, receipts and invoices
    po_happy = order_from(
        erp, "PO-HAPPY", mr_happy, "LabChem Supply Co", "2026-08-05",
        {"LC-PASTE": 38, "LC-RIFLUID": 105},
    )  # fmt: skip
    pr_happy = receive(erp, "PR-HAPPY", po_happy, "2026-08-12")
    pi_happy = invoice(
        erp, "PI-HAPPY", ("Purchase Receipt", pr_happy), "LC-INV-4410", "2026-08-13", submit=True
    )
    pay(erp, "PE-HAPPY", pi_happy, "2026-09-10")

    po_micro = order(
        erp, "PO-MICRO", "GemTech Instruments", "2026-09-15",
        [line("LE-MICRO", 2, 6500, "Gemology Research", "New York Lab", g1, "2026-10-01")],
    )  # fmt: skip
    receive(erp, "PR-MICRO", po_micro, "2026-10-02", qty={"LE-MICRO": 1})  # one short
    invoice(erp, "PI-MICRO", ("Purchase Order", po_micro), "GT-77812", "2026-10-05")  # bills 2

    po_lamp = order(
        erp, "PO-LAMP", "Precision Optics Inc", "2026-09-20",
        [line("LC-LAMP", 50, 12, "Grading Operations", "Carlsbad Lab", None, "2026-10-01")],
    )  # fmt: skip
    pr_lamp = receive(erp, "PR-LAMP", po_lamp, "2026-10-01")
    invoice(  # 9% above the PO price
        erp, "PI-LAMP", ("Purchase Receipt", pr_lamp), "PO-INV-2207", "2026-10-03",
        rates={"LC-LAMP": 13.10},
    )  # fmt: skip

    po_calib = order(
        erp, "PO-CALIB", "CalibrateRight Services", "2026-10-01",
        [line("SV-CALIB", 1, 2400, "Facilities", "Antwerp Lab", None, "2026-10-15")],
    )  # fmt: skip
    invoice(erp, "PI-CALIB", ("Purchase Order", po_calib), "CR-1093", "2026-10-20")  # unconfirmed

    po_print = order(
        erp, "PO-PRINT", "Pacific IT Solutions", "2026-10-10",
        [line("IT-BARCODE", 3, 640, "IT", "Carlsbad Lab", None, "2026-10-20")],
    )  # fmt: skip
    receive(erp, "PR-PRINT", po_print, "2026-10-22")  # received, not invoiced yet: an accrual

    po_gloves = order(
        erp, "PO-GLOVES", "LabChem Supply Co", "2026-09-01",
        [line("LC-GLOVES", 60, 12.90, *pearl, None, "2026-09-10")],
    )  # fmt: skip
    pr_gloves = receive(erp, "PR-GLOVES", po_gloves, "2026-09-09")
    gloves = ("Purchase Receipt", pr_gloves)
    first = invoice(erp, "PI-GLOVES", gloves, "LC-INV-4502", "2026-09-10", submit=True)
    resend(erp, "PI-GLOVES-DUP", first, "2026-10-28")  # the supplier sent the same bill again

    po_bags = order(
        erp, "PO-BAGS", "LabChem Supply Co", "2026-10-12",
        [line("LC-BAGS", 25, 32, "Grading Operations", "Mumbai Lab", None, "2026-10-20")],
    )  # fmt: skip
    pr_bags = receive(erp, "PR-BAGS", po_bags, "2026-10-19")
    invoice(erp, "PI-BAGS", ("Purchase Receipt", pr_bags), "LC-INV-4611", "2026-10-21")  # clean

    # AP-6: a service delivered and confirmed, not billed yet (no GL until billed: an accrual)
    po_maint = order(
        erp, "PO-MAINT", "CalibrateRight Services", "2026-10-20",
        [line("SV-MAINT", 1, 1800, "Facilities", "Antwerp Lab", None, "2026-10-28")],
    )  # fmt: skip
    receive(erp, "PR-MAINT", po_maint, "2026-10-28")
    # ...and a rebate journalled straight to the supplier's account: the AP subledger (bills)
    # and the Creditors ledger now differ by it
    if not seeded(erp, "Journal Entry", "JE-REBATE"):
        je = erp.insert(
            {"doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": COMPANY,
             "posting_date": "2026-10-30", "seed_ref": "JE-REBATE",
             "user_remark": "Volume rebate agreed with LabChem by phone",
             "accounts": [
                 {"account": acct("Creditors"), "party_type": "Supplier",
                  "party": "LabChem Supply Co", "debit_in_account_currency": 100},
                 {"account": acct("Miscellaneous Expenses"), "cost_center": cc("Facilities"),
                  "credit_in_account_currency": 100},
             ]}
        )  # fmt: skip
        erp.submit("Journal Entry", je["name"])

    order(  # open: nothing received or billed yet
        erp, "PO-PAPER", "Summit Office Supplies", "2026-10-25",
        [line("OF-PAPER", 20, 38, "Facilities", "New York Lab", None, "2026-11-15")],
    )  # fmt: skip

    # A non-PO invoice (its coding comes from history, AP-4)
    if not seeded(erp, "Purchase Invoice", "PI-NONPO"):
        erp.insert(
            {"doctype": "Purchase Invoice", "supplier": "CalibrateRight Services",
             "company": COMPANY, "seed_ref": "PI-NONPO", "bill_no": "CR-1101",
             "bill_date": "2026-10-30", "posting_date": "2026-10-30", "set_posting_time": 1,
             "items": [{"item_code": "SV-MAINT", "qty": 1, "rate": 1800, "uom": "Nos",
                        "conversion_factor": 1, "cost_center": cc("Facilities"),
                        "lab": "New York Lab",
                        "expense_account": acct("Professional Services")}]}
        )  # fmt: skip

    if not erp.find("Note", {"title": MARKER}):
        erp.insert({"doctype": "Note", "title": MARKER, "public": 0,
                    "content": "Demo transactions created by scripts/erpnext_seed.py"})  # fmt: skip


# --- Order-to-Cash (AR): clients, lab submissions, invoices, payments -----------------------
# The lab system isn't connected: a Sales Order stands in for a lab submission, its custom
# "Report issued on" date for the lab's report-issued event, its "Fee estimate" for the fee
# the client saw when submitting.

AR_MARKER = "finance-acc-ar-seed"
INCOME = acct("Service")
TAX_DOMESTIC = "US ST 6.25% - GIAD"

# code, name, standard selling rate (an added service may be added in the lab)
SERVICES = (
    ("GR-DIA", "Diamond Grading Report", 150.00),
    ("GR-DOS", "Diamond Dossier", 90.00),
    ("ID-COL", "Colored Stone Identification Report", 120.00),
    ("ID-PEARL", "Pearl Identification Report", 110.00),
    ("SV-LASER", "Laser inscription (added service)", 40.00),
    ("SV-RUSH", "Rush turnaround (added service)", 75.00),
    ("SV-RECHECK", "Report re-check", 60.00),
)

# name, territory, tax category, terms (days), credit limit (None: deposit only), email,
# flags (key account, frozen = on hold)
CLIENTS = (
    ("Brilliant Gems LLC", "United States", "Domestic", 30, 50000,
     "ap@brilliantgems.example.com", {}),
    ("Rivera Fine Jewelry", "United States", "Domestic", 30, 15000,
     "accounts@riverafj.example.com", {}),
    ("Antwerp Diamond House", "Rest Of The World", "Export", 45, 30000,
     "finance@antwerpdh.example.com", {}),
    ("Sapphire & Co Jewelers", "United States", "Domestic", 30, 40000,
     "payables@sapphireco.example.com", {"key_account": 1}),
    ("Pearl Street Traders", "United States", "Domestic", 0, None,
     "office@pearlstreet.example.com", {"deposit_only": 1}),
    ("Crown Estate Jewels", "United States", "Domestic", 30, 10000,
     "billing@crownestate.example.com", {}),  # put on hold once billed
    ("Northstar Retail", "United States", "Domestic", 30, 5000, None, {}),  # no contact yet
)  # fmt: skip


def terms_template(erp: Erp, days: int) -> str:
    name = "Due on receipt" if days == 0 else f"Net {days}"
    if not erp.find("Payment Terms Template", {"name": name}):
        erp.insert(
            {"doctype": "Payment Terms Template", "template_name": name,
             "terms": [{"invoice_portion": 100, "credit_days": days,
                        "due_date_based_on": "Day(s) after invoice date",
                        "description": name}]}
        )  # fmt: skip
    return name


def receivables_masters(erp: Erp) -> None:
    print("AR masters: lab services, prices, tax categories, terms, clients...")
    custom_field(erp, "Customer", "deposit_only", "Deposit only (no credit)", "Check",
                 "customer_group")  # fmt: skip
    custom_field(erp, "Customer", "key_account", "Key account", "Check", "deposit_only")
    custom_field(erp, "Sales Order", "report_issued_on", "Report issued on", "Date",
                 "delivery_date")  # fmt: skip
    custom_field(erp, "Sales Order", "fee_estimate", "Fee estimate", "Currency",
                 "report_issued_on")  # fmt: skip
    custom_field(erp, "Sales Order Item", "added_service", "Added in the lab", "Check",
                 "item_name")  # fmt: skip
    for dt in ("Sales Order", "Sales Invoice"):
        custom_field(erp, dt, "seed_ref", "Demo seed reference", "Data", "naming_series")
    for dt in ("Customer", "Sales Invoice", "Payment Entry"):
        custom_field(erp, dt, "finance_acc_ref", "Finance ACC reference", "Data", "naming_series")

    erp.ensure({"doctype": "Item Group", "item_group_name": "Lab Services",
                "parent_item_group": "All Item Groups"}, {"name": "Lab Services"})  # fmt: skip
    for code, name, rate in SERVICES:
        erp.ensure(
            {"doctype": "Item", "item_code": code, "item_name": name, "item_group": "Lab Services",
             "stock_uom": "Nos", "is_stock_item": 0, "is_purchase_item": 0, "is_sales_item": 1,
             "include_item_in_manufacturing": 0,
             "item_defaults": [{"company": COMPANY, "income_account": INCOME}]},
            {"name": code},
        )  # fmt: skip
        erp.ensure(
            {"doctype": "Item Price", "item_code": code, "price_list": "Standard Selling",
             "price_list_rate": rate, "uom": "Nos"},
            {"item_code": code, "price_list": "Standard Selling", "customer": ["is", "not set"]},
        )  # fmt: skip

    for category in ("Domestic", "Export"):
        erp.ensure({"doctype": "Tax Category", "title": category}, {"name": category})
    erp.update("Sales Taxes and Charges Template", TAX_DOMESTIC, {"tax_category": "Domestic"})
    erp.ensure(
        {"doctype": "Sales Taxes and Charges Template", "title": "Export 0%", "company": COMPANY,
         "tax_category": "Export",
         "taxes": [{"charge_type": "On Net Total", "account_head": acct("ST 6%"), "rate": 0,
                    "description": "Export of services: zero-rated"}]},
        {"title": "Export 0%"},
    )  # fmt: skip

    for name, territory, category, days, limit, email, flags in CLIENTS:
        erp.ensure(
            {"doctype": "Customer", "customer_name": name, "customer_type": "Company",
             "customer_group": "Commercial", "territory": territory, "tax_category": category,
             "payment_terms": terms_template(erp, days), "default_currency": "USD",
             "credit_limits": [{"company": COMPANY, "credit_limit": limit}] if limit else [],
             **flags},
            {"name": name},
        )  # fmt: skip
        if email:
            erp.ensure(
                {"doctype": "Contact", "first_name": "Accounts", "last_name": name,
                 "email_ids": [{"email_id": email, "is_primary": 1}],
                 "links": [{"link_doctype": "Customer", "link_name": name}],
                 "is_primary_contact": 1},
                {"email_id": email},
            )  # fmt: skip
    # A trade discount (contract price) and a client's own price
    erp.ensure(
        {"doctype": "Pricing Rule", "title": "Brilliant Gems trade discount", "company": COMPANY,
         "apply_on": "Item Group", "item_groups": [{"item_group": "Lab Services"}],
         "selling": 1, "applicable_for": "Customer", "customer": "Brilliant Gems LLC",
         "rate_or_discount": "Discount Percentage", "discount_percentage": 10,
         "valid_from": "2026-01-01"},
        {"title": "Brilliant Gems trade discount"},
    )  # fmt: skip
    erp.ensure(
        {"doctype": "Item Price", "item_code": "GR-DIA", "price_list": "Standard Selling",
         "price_list_rate": 135, "uom": "Nos", "customer": "Sapphire & Co Jewelers"},
        {"item_code": "GR-DIA", "price_list": "Standard Selling",
         "customer": "Sapphire & Co Jewelers"},
    )  # fmt: skip


SalesLine = tuple[str, float, float, bool]  # item, qty, rate, added in the lab


def _sales_lines(lines: list[SalesLine], date: str) -> list[dict[str, Any]]:
    return [
        {"item_code": code, "qty": qty, "rate": rate, "delivery_date": date, "uom": "Nos",
         "conversion_factor": 1, "income_account": INCOME, "added_service": int(added)}
        for code, qty, rate, added in lines
    ]  # fmt: skip


def submission(erp: Erp, ref: str, client: str, date: str, lines: list[SalesLine],
               estimate: float, issued: str | None) -> str:  # fmt: skip
    """A lab submission (Sales Order): what the client handed in, the fee estimate they saw,
    and the date the lab issued the report (None: still in the lab)."""
    if found := seeded(erp, "Sales Order", ref):
        return found
    doc = erp.insert(
        {"doctype": "Sales Order", "customer": client, "company": COMPANY,
         "transaction_date": date, "delivery_date": date, "ignore_pricing_rule": 1,
         "items": _sales_lines(lines, date), "fee_estimate": estimate,
         "report_issued_on": issued, "seed_ref": ref}
    )  # fmt: skip
    erp.submit("Sales Order", doc["name"])
    return str(doc["name"])


def sales_invoice(erp: Erp, ref: str, client: str, date: str,
                  lines: list[SalesLine]) -> str:  # fmt: skip
    """A posted invoice of an earlier submission; its due date follows the client's terms."""
    if found := seeded(erp, "Sales Invoice", ref):
        return found
    category = next(c[2] for c in CLIENTS if c[0] == client)
    template = TAX_DOMESTIC if category == "Domestic" else "Export 0% - GIAD"
    taxes = erp.get("Sales Taxes and Charges Template", template)["taxes"]
    doc = erp.insert(
        {"doctype": "Sales Invoice", "customer": client, "company": COMPANY,
         "posting_date": date, "set_posting_time": 1, "ignore_pricing_rule": 1,
         "taxes_and_charges": template,
         "taxes": [{k: t[k] for k in ("charge_type", "account_head", "rate", "description")}
                   for t in taxes],
         "items": _sales_lines(lines, date), "seed_ref": ref}
    )  # fmt: skip
    erp.submit("Sales Invoice", doc["name"])
    return str(doc["name"])


def receive_payment(erp: Erp, ref: str, si: str, date: str, amount: float | None = None) -> None:
    if seeded(erp, "Payment Entry", ref):
        return
    pe = erp.call(
        "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
        dt="Sales Invoice", dn=si,
    )  # fmt: skip
    if amount is not None:
        pe["paid_amount"] = pe["received_amount"] = amount
        pe["references"][0]["allocated_amount"] = amount
    pe.update({"posting_date": date, "reference_no": f"WIRE-{si[-5:]}", "reference_date": date,
               "seed_ref": ref})  # fmt: skip
    name = erp.insert(pe)["name"]
    erp.submit("Payment Entry", name)


def receivables(erp: Erp) -> None:
    receivables_masters(erp)
    if erp.find("Note", {"title": AR_MARKER}):
        print("AR transactions already seeded (Note finance-acc-ar-seed): skipped.")
        return
    print("AR transactions: submissions, invoices across the ageing buckets, payments...")
    # AR-3: submissions whose report is issued and not billed yet
    submission(
        erp,
        "SO-BRILLIANT",
        "Brilliant Gems LLC",
        "2026-10-26",
        [("GR-DIA", 10, 150, False)],
        1500,
        "2026-10-30",
    )  # clean; 10% trade discount
    submission(
        erp,
        "SO-RIVERA",
        "Rivera Fine Jewelry",
        "2026-10-24",
        [("ID-COL", 5, 120, False), ("SV-LASER", 5, 40, True)],
        600,
        "2026-10-31",
    )  # an added service: over the estimate
    submission(
        erp,
        "SO-ANTWERP",
        "Antwerp Diamond House",
        "2026-10-27",
        [("GR-DOS", 3, 90, False)],
        270,
        "2026-11-01",
    )  # export: zero-rated
    submission(
        erp,
        "SO-SAPPHIRE",
        "Sapphire & Co Jewelers",
        "2026-10-29",
        [("GR-DIA", 4, 135, False), ("SV-RUSH", 4, 75, True)],
        540,
        "2026-11-02",
    )  # the client's own price, and a rush added
    submission(
        erp,
        "SO-INLAB",
        "Sapphire & Co Jewelers",
        "2026-11-01",
        [("ID-PEARL", 6, 110, False)],
        660,
        None,
    )  # still in the lab: not billable

    # AR-5: history and open items (as of early November 2026)
    paid = sales_invoice(erp, "SI-BRILLIANT-SEP", "Brilliant Gems LLC", "2026-09-20",
                         [("GR-DIA", 10, 135, False)])  # fmt: skip
    receive_payment(erp, "PE-BRILLIANT-SEP", paid, "2026-10-15")  # on time
    sales_invoice(erp, "SI-BRILLIANT-OCT", "Brilliant Gems LLC", "2026-10-20",
                  [("GR-DIA", 8, 135, False)])  # current, not due  # fmt: skip
    partly = sales_invoice(erp, "SI-RIVERA-SEP", "Rivera Fine Jewelry", "2026-09-10",
                           [("ID-COL", 15, 120, False)])  # 1-30 days overdue  # fmt: skip
    receive_payment(erp, "PE-RIVERA-PART", partly, "2026-10-20", 800)
    sales_invoice(erp, "SI-RIVERA-AUG", "Rivera Fine Jewelry", "2026-08-15",
                  [("ID-COL", 10, 120, False)])  # 31-60 days overdue  # fmt: skip
    late = sales_invoice(erp, "SI-ANTWERP-MAY", "Antwerp Diamond House", "2026-05-10",
                         [("GR-DOS", 20, 90, False)])  # fmt: skip
    receive_payment(erp, "PE-ANTWERP-LATE", late, "2026-07-30")  # paid 36 days late
    sales_invoice(erp, "SI-ANTWERP-JUL", "Antwerp Diamond House", "2026-07-05",
                  [("GR-DOS", 40, 90, False)])  # 61-90 days overdue  # fmt: skip
    sales_invoice(erp, "SI-SAPPHIRE-JUN", "Sapphire & Co Jewelers", "2026-06-10",
                  [("GR-DIA", 80, 135, False)])  # 90+ days, key account  # fmt: skip
    sales_invoice(erp, "SI-SAPPHIRE-SEP", "Sapphire & Co Jewelers", "2026-09-01",
                  [("GR-DIA", 40, 135, False)])  # 31-60  # fmt: skip
    erp.update("Customer", "Crown Estate Jewels", {"is_frozen": 0})  # a rerun after a failure
    sales_invoice(erp, "SI-CROWN-MAY", "Crown Estate Jewels", "2026-05-01",
                  [("ID-COL", 30, 120, False)])  # 90+, account on hold  # fmt: skip
    # ERPNext won't invoice a frozen client: Crown goes on hold after its old invoice
    erp.update("Customer", "Crown Estate Jewels", {"is_frozen": 1})
    erp.insert({"doctype": "Note", "title": AR_MARKER, "public": 0,
                "content": "AR demo transactions created by scripts/erpnext_seed.py"})  # fmt: skip


# --- more work to do: a fresh batch for the demo -------------------------------------------
# Every seeded invoice and submission ends up with a case; --more adds a new batch (its own
# refs, so it can be run again and again) for new invoice-matching and billing cases.

TOPUP = "finance-acc-topup"


def topup(erp: Erp) -> None:
    batch = len(erp.http.get("/api/resource/Note", params={
        "filters": json.dumps([["title", "like", f"{TOPUP}-%"]]), "limit_page_length": 0,
    }).json()["data"]) + 1  # fmt: skip
    tag = f"T{batch}"
    print(f"More work (batch {tag}): supplier invoices to match, submissions to bill...")
    # AP-3: a clean three-way match, and one billed above the PO price
    po = order(
        erp, f"PO-{tag}-TUBES", "LabChem Supply Co", "2026-10-26",
        [line("LC-BAGS", 30, 32, "Grading Operations", "Mumbai Lab", None, "2026-11-01")],
    )  # fmt: skip
    pr = receive(erp, f"PR-{tag}-TUBES", po, "2026-10-31")
    invoice(erp, f"PI-{tag}-TUBES", ("Purchase Receipt", pr), f"LC-INV-{4700 + batch}",
            "2026-11-02")  # clean  # fmt: skip
    po = order(
        erp, f"PO-{tag}-LAMP", "Precision Optics Inc", "2026-10-25",
        [line("LC-LAMP", 40, 12, "Grading Operations", "Carlsbad Lab", None, "2026-11-01")],
    )  # fmt: skip
    pr = receive(erp, f"PR-{tag}-LAMP", po, "2026-10-30")
    invoice(erp, f"PI-{tag}-LAMP", ("Purchase Receipt", pr), f"PO-INV-{2300 + batch}",
            "2026-11-02", rates={"LC-LAMP": 12.80})  # 6.7% above the PO  # fmt: skip
    # AR-3: reports issued, not billed
    submission(erp, f"SO-{tag}-BRILLIANT", "Brilliant Gems LLC", "2026-10-28",
               [("GR-DIA", 6, 150, False)], 900, "2026-11-02")  # clean  # fmt: skip
    submission(erp, f"SO-{tag}-RIVERA", "Rivera Fine Jewelry", "2026-10-29",
               [("ID-COL", 4, 120, False), ("SV-RUSH", 4, 75, True)], 480,
               "2026-11-02")  # a rush added: over the estimate  # fmt: skip
    submission(erp, f"SO-{tag}-ANTWERP", "Antwerp Diamond House", "2026-10-30",
               [("GR-DOS", 5, 90, False)], 450, "2026-11-03")  # export  # fmt: skip
    erp.insert({"doctype": "Note", "title": f"{TOPUP}-{tag}", "public": 0,
                "content": "More demo work created by scripts/erpnext_seed.py --more"})  # fmt: skip


# --- the app's API user --------------------------------------------------------------------


def api_user(erp: Erp, new_keys: bool) -> None:
    if not erp.find("User", {"name": API_USER}):
        erp.insert(
            {"doctype": "User", "email": API_USER, "first_name": "Finance ACC",
             "last_name": "Integration", "user_type": "System User", "send_welcome_email": 0,
             "roles": [{"role": r} for r in API_ROLES]}
        )  # fmt: skip
        new_keys = True
    else:  # keep its roles current
        erp.update("User", API_USER, {"roles": [{"role": r} for r in API_ROLES]})
    key, secret = os.environ.get("ERPNEXT_API_KEY"), os.environ.get("ERPNEXT_API_SECRET")
    if key and secret and not new_keys:
        _fixed_keys(erp, key, secret)
        return
    if not new_keys:
        print(f"\nAPI user {API_USER} exists. Run with --new-keys for a new secret.")
        return
    secret = erp.call("frappe.core.doctype.user.user.generate_keys", user=API_USER)["api_secret"]
    key = erp.get("User", API_USER)["api_key"]
    print("\nERPNext API credentials for the app (the secret is shown once):")
    print(f"  ERPNEXT_URL={URL}")
    print(f"  ERPNEXT_API_KEY={key}")
    print(f"  ERPNEXT_API_SECRET={secret}")


def _fixed_keys(erp: Erp, key: str, secret: str) -> None:
    """The API user gets the key/secret the app is configured with (docker compose: dev
    defaults), unless it already has them."""
    probe = httpx.get(f"{URL}/api/method/frappe.auth.get_logged_user",
                      headers={"Authorization": f"token {key}:{secret}"}, timeout=60)  # fmt: skip
    if probe.status_code == 200 and probe.json().get("message") == API_USER:
        print(f"\nAPI user {API_USER} already has ERPNEXT_API_KEY's key.")
        return
    erp.update("User", API_USER, {"api_key": key, "api_secret": secret})
    print(f"\nAPI user {API_USER} now has ERPNEXT_API_KEY / ERPNEXT_API_SECRET.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the local ERPNext with GIA demo data.")
    parser.add_argument("--new-keys", action="store_true", help="issue a new API secret")
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        metavar="SECONDS",
        help="wait this long for ERPNext to come up (a new site takes minutes)",
    )
    parser.add_argument(
        "--more",
        action="store_true",
        help="add a new batch of invoices to match and submissions to bill",
    )
    args = parser.parse_args()
    erp = Erp()
    try:
        erp.login(args.wait)
        setup_company(erp)
        transactions(erp, masters(erp))
        receivables(erp)
        if args.more:
            topup(erp)
        api_user(erp, args.new_keys)
    except (ErpError, httpx.HTTPError) as exc:
        sys.exit(f"ERPNext seed failed: {exc}")
    print(f"\nDone. ERPNext: {URL} (Administrator / your ERPNEXT_ADMIN_PASSWORD).")


if __name__ == "__main__":
    main()
