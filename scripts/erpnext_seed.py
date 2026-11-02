"""Seed the local ERPNext (ops/erpnext) with a GIA-like demo company for the Finance POD.

    uv run poe erpnext-seed              # setup wizard, masters, transactions, API user
    uv run poe erpnext-seed --new-keys   # also issue a new API secret for the app

ERPNext v16's own demo data is only a few masters (3 suppliers, 10 items, no transactions),
so this builds what the AP agents need, every figure fictional and every email @example.com:

- Masters: company "GIA Demo Labs" (USD, fiscal year 2026); labs (Branch, used as the "Lab"
  accounting dimension); departments (cost centres); grants (Projects with funder, period,
  restricted fund and allowed item groups); expense accounts; items with standard and
  supplier contract prices; suppliers (approved, one blocked, one on hold, one without an
  email); a framework contract; budgets per department and grant (one nearly used up).
- AP-1: purchase requests (approved, draft, urgent, without a grant), and a high-value
  request with three supplier quotations waiting for the buyer.
- AP-3: purchase orders and receipts, and incoming supplier invoices (drafts) that match,
  carry a price variance, bill more than was received, have no receipt, duplicate a posted
  one, or have no PO at all.
- AP-6: goods received and not invoiced (accruals), posted invoices and a payment.

Masters are get-or-create, so reruns are safe; transactions are created once (a Note named
"finance-acc-demo-seed" marks it). Talks to ERPNext's REST API only.
"""

import argparse
import json
import os
import sys
import time
from typing import Any

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
    "Projects User", "HR User",
)  # fmt: skip


class ErpError(RuntimeError):
    pass


class Erp:
    def __init__(self) -> None:
        self.http = httpx.Client(base_url=URL, timeout=300)

    def login(self) -> None:
        r = self.http.post(
            "/api/method/login", json={"usr": "Administrator", "pwd": ADMIN_PASSWORD}
        )
        if r.status_code != 200:
            raise ErpError(f"Can't sign in to ERPNext at {URL}: {r.text[:200]}")

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
        doc: dict[str, Any] = self._check(self.http.get(f"/api/resource/{doctype}/{name}"))["data"]
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
            self.http.put(f"/api/resource/{doctype}/{name}", json={"docstatus": 1})
        )["data"]
        return out

    def update(self, doctype: str, name: str, values: dict[str, Any]) -> None:
        self._check(self.http.put(f"/api/resource/{doctype}/{name}", json=values))


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
               "Purchase Invoice", "Payment Entry", "Note"):  # fmt: skip
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
    if erp.find("Note", {"title": MARKER}):
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

    erp.insert({"doctype": "Note", "title": MARKER, "public": 0,
                "content": "Demo transactions created by scripts/erpnext_seed.py"})  # fmt: skip


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
    if not new_keys:
        print(f"\nAPI user {API_USER} exists. Run with --new-keys for a new secret.")
        return
    secret = erp.call("frappe.core.doctype.user.user.generate_keys", user=API_USER)["api_secret"]
    key = erp.get("User", API_USER)["api_key"]
    print("\nERPNext API credentials for the app (the secret is shown once):")
    print(f"  ERPNEXT_URL={URL}")
    print(f"  ERPNEXT_API_KEY={key}")
    print(f"  ERPNEXT_API_SECRET={secret}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the local ERPNext with GIA demo data.")
    parser.add_argument("--new-keys", action="store_true", help="issue a new API secret")
    args = parser.parse_args()
    erp = Erp()
    try:
        erp.login()
        setup_company(erp)
        transactions(erp, masters(erp))
        api_user(erp, args.new_keys)
    except (ErpError, httpx.HTTPError) as exc:
        sys.exit(f"ERPNext seed failed: {exc}")
    print(f"\nDone. ERPNext: {URL} (Administrator / your ERPNEXT_ADMIN_PASSWORD).")


if __name__ == "__main__":
    main()
