"""ERPNext: connecting a site, freezing a snapshot of its purchasing data, and the app
posting an approved task to it (once, even when retried), verified by a fresh snapshot.
ERPNext is a stand-in (fake_erpnext.py): no test talks to a real site."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.data_sources.models import DataSource
from src.app.data_sources.providers import erpnext as provider
from src.app.entities.models import LegalEntity
from src.app.service_pod.core.hooks import HOOKS
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.snapshots.service import stored_payload
from src.app.service_pod.core.steps.spec import StepPlan
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey
from tests.finance_pod.conftest import DEMO_KEY, DEMO_SPEC
from tests.finance_pod.fake_erpnext import COMPANY, KEY, SECRET, FakeErpNext
from tests.service_pod.conftest import snapshot_payload

BASE = "http://erp.example.test"


@pytest.fixture
def erp(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeErpNext]:
    fake = FakeErpNext()
    monkeypatch.setattr(provider, "transport", httpx.MockTransport(fake.handler))
    yield fake


async def _connect(client: AsyncClient, **changes: Any) -> Any:
    body = {"name": "GIA ERPNext", "base_url": BASE, "api_key": KEY, "api_secret": SECRET,
            "company": COMPANY, "environment": "sandbox", **changes}  # fmt: skip
    return await client.post("/api/v1/data-sources/erpnext", json=body)


async def _snapshot(client: AsyncClient, source: dict[str, Any], entity: LegalEntity) -> Any:
    return await client.post(
        "/api/v1/pod/snapshots/erpnext",
        json={"data_source_id": source["id"], "entity_id": str(entity.id)},
    )


async def test_connecting_checks_the_key_and_company_and_hides_the_secret(
    admin: AsyncClient, erp: FakeErpNext, db: AsyncSession
) -> None:
    r = await _connect(admin, api_secret="wrong")
    assert r.status_code == 422
    assert "refused the API key" in r.json()["detail"]["message"]
    r = await _connect(admin, company="Nope Inc")
    assert r.status_code == 422
    assert "exact name" in r.json()["detail"]["message"]
    r = await _connect(admin, base_url="ftp://erp.example.test")
    assert r.status_code == 422

    r = await _connect(admin)
    assert r.status_code == 201, r.text
    source = r.json()
    assert (source["kind"], source["status"], source["base_url"]) == ("erpnext", "connected", BASE)
    assert source["external_id"] == COMPANY
    assert "secret" not in r.text.lower().replace("client_secret", "")
    row = await db.scalar(select(DataSource).where(DataSource.kind == "erpnext"))
    assert row is not None and row.client_secret_enc and SECRET not in row.client_secret_enc

    erp.key = "rotated"  # the site revoked the key
    r = await admin.post(f"/api/v1/data-sources/{source['id']}/sync")
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["last_error"]) == (
        "error",
        "ERPNext refused the API key and secret.",
    )


async def test_connecting_syncs_records_like_quickbooks(
    admin: AsyncClient, erp: FakeErpNext
) -> None:
    source = (await _connect(admin)).json()
    assert source["record_counts"] == {
        "vendor": 2, "account": 2, "purchase_order": 1, "bill": 1,
    }  # fmt: skip
    assert source["last_error"] is None
    bills = (await admin.get(f"/api/v1/data-sources/{source['id']}/records?type=bill")).json()
    assert [(b["reference"], b["counterparty"], b["amount"]) for b in bills] == [
        ("LC-77", "LabChem Supply Co", "760.00")
    ]
    assert bills[0]["data"]["po_number"] == "PO-1"
    assert bills[0]["data"]["balance"] == "760.00"
    vendors = (await admin.get(f"/api/v1/data-sources/{source['id']}/records?type=vendor")).json()
    assert {v["reference"]: v["data"]["active"] for v in vendors} == {
        "LabChem Supply Co": True,
        "Shadow Trading LLC": False,
    }
    orders = (
        await admin.get(f"/api/v1/data-sources/{source['id']}/records?type=purchase_order")
    ).json()
    assert orders[0]["data"]["received_amount"] == "380.00"  # 1 of 2 received


def test_production_needs_https_and_an_allowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "erpnext_allowed_hosts", "erp.gia.example")
    assert provider.check_base_url("https://erp.gia.example/app") == "https://erp.gia.example"
    with pytest.raises(provider.ErpNextError, match="isn't allowed"):
        provider.check_base_url("https://internal.service")
    monkeypatch.setattr(type(settings), "is_production", property(lambda _: True))
    with pytest.raises(provider.ErpNextError, match="https"):
        provider.check_base_url("http://erp.gia.example")


async def test_a_snapshot_holds_the_purchasing_data(
    admin: AsyncClient, erp: FakeErpNext, entity: LegalEntity
) -> None:
    source = (await _connect(admin)).json()
    r = await _snapshot(admin, source, entity)
    assert r.status_code == 201, r.text
    snap = r.json()["snapshot"]
    assert snap["is_demo"] is True  # a sandbox connection
    assert snap["source_type"] == "erpnext"
    assert snap["row_counts"] == {
        "accounts": 2, "vendors": 2, "items": 4, "item_prices": 2, "vendor_contracts": 1,
        "cost_centres": 1, "labs": 1, "grants": 1, "budgets": 1, "budget_actuals": 1,
        "purchase_requests": 1, "supplier_quotations": 1, "purchase_orders": 1,
        "purchase_receipts": 1, "bills": 1, "ledger_balances": 1, "ledger_entries": 0,
        "journal_entries": 0, "clients": 2, "submissions": 1, "sales_invoices": 1,
        "client_payments": 1, "selling_prices": 2, "price_rules": 1, "tax_rules": 1,
    }  # fmt: skip

    rows = (await admin.get(f"/api/v1/pod/snapshots/{snap['id']}/rows?collection=vendors")).json()
    vendors = {v["id"]: v for v in rows["rows"]}
    assert vendors["LabChem Supply Co"]["email"] == "orders@labchem.example.com"
    assert vendors["Shadow Trading LLC"] == {**vendors["Shadow Trading LLC"],
                                             "status": "Disabled", "email": None}  # fmt: skip
    orders = (
        await admin.get(f"/api/v1/pod/snapshots/{snap['id']}/rows?collection=purchase_orders")
    ).json()
    line = orders["rows"][0]["lines"][0]
    assert line["request_id"] is None  # its request is older than the read window
    assert (line["received_qty"], line["lab_id"], line["grant_id"]) == (
        "1",
        "Carlsbad Lab",
        "PROJ-0001",
    )
    actuals = (
        await admin.get(f"/api/v1/pod/snapshots/{snap['id']}/rows?collection=budget_actuals")
    ).json()
    assert actuals["rows"][0]["amount"] == "1200"
    contracts = (
        await admin.get(f"/api/v1/pod/snapshots/{snap['id']}/rows?collection=vendor_contracts")
    ).json()
    assert contracts["rows"][0]["terms"] == "Framework agreement"

    again = await _snapshot(admin, source, entity)
    assert (again.status_code, again.json()["created"]) == (200, False)


async def test_a_snapshot_holds_the_receivables_data(
    admin: AsyncClient, erp: FakeErpNext, entity: LegalEntity
) -> None:
    source = (await _connect(admin)).json()
    snap = (await _snapshot(admin, source, entity)).json()["snapshot"]

    async def rows(collection: str) -> list[dict[str, Any]]:
        url = f"/api/v1/pod/snapshots/{snap['id']}/rows?collection={collection}"
        found: list[dict[str, Any]] = (await admin.get(url)).json()["rows"]
        return found

    items = {i["code"]: i for i in await rows("items")}
    assert (items["GR-DIA"]["purchasable"], items["GR-DIA"]["sellable"]) == (False, True)
    assert (items["LC-PASTE"]["purchasable"], items["LC-PASTE"]["sellable"]) == (True, False)
    catalogue = await admin.get(
        f"/api/v1/finance/sources/{snap['id']}/catalogue?workflow=ap_purchase_request"
    )
    assert "GR-DIA" not in {i["code"] for i in catalogue.json()["items"]}  # sold, not bought
    clients = {c["id"]: c for c in await rows("clients")}
    brilliant = clients["Brilliant Gems"]
    assert (brilliant["name"], brilliant["email"], brilliant["credit_limit"]) == (
        "Brilliant Gems LLC", "ap@brilliantgems.example.com", "50000",
    )  # fmt: skip
    assert (brilliant["terms_days"], brilliant["key_account"], brilliant["status"]) == (
        30, True, "Active",
    )  # fmt: skip
    crown = clients["Crown Estate"]
    assert (crown["status"], crown["credit_limit"], crown["email"]) == ("On hold", None, None)

    (submission,) = await rows("submissions")
    assert (submission["report_issued_on"], submission["fee_estimate"]) == ("2026-10-30", "300")
    assert [ln["added"] for ln in submission["lines"]] == [False, True]
    (invoice,) = await rows("sales_invoices")
    assert (invoice["outstanding"], invoice["tax_total"], invoice["due_date"]) == (
        "118.75", "18.75", "2026-10-20",
    )  # fmt: skip
    assert invoice["lines"][0]["submission_id"] is None  # its order is older than the window
    (payment,) = await rows("client_payments")
    assert payment["allocations"] == [{"invoice_id": "SI-1", "amount": "200"}]
    prices = {(p["item_code"], p["client_id"]): p["rate"] for p in await rows("selling_prices")}
    assert prices == {("GR-DIA", None): "150", ("GR-DIA", "Brilliant Gems"): "135"}
    (rule,) = await rows("price_rules")
    assert (rule["item_group"], rule["client_id"], rule["discount_pct"]) == (
        "Lab Services", "Brilliant Gems", "10",
    )  # fmt: skip
    (tax,) = await rows("tax_rules")
    assert (tax["id"], tax["tax_category"], tax["rate_pct"]) == (
        "US ST 6.25% - GIAD", "Domestic", "6.25",
    )  # fmt: skip


async def test_only_your_own_connection_can_be_read(
    admin: AsyncClient, erp: FakeErpNext, entity: LegalEntity, make_user: Any,
    signed_in_client: Any,
) -> None:  # fmt: skip
    from src.app.auth.models import UserRole

    other = await signed_in_client(await make_user("fa2@example.com", UserRole.FINANCE_ADMIN))
    source = (await _connect(admin)).json()
    assert (await _snapshot(other, source, entity)).status_code == 404


def test_the_contract_refuses_dangling_links() -> None:
    item = {"code": "A", "name": "A", "group": "G", "stock_item": True}
    base = {"provenance": "SYNTHETIC_DEMO", "company_id": "x", "company_name": "x",
            "entity": "US01", "currency": "USD", "basis": "Accrual", "as_of": "2026-11-03",
            "source_reference": "t", "vendors": [], "items": [item]}  # fmt: skip
    line = {"id": "l1", "item_code": "A", "qty": "1", "rate": "10", "amount": "10"}
    order = {"id": "PO-1", "vendor_id": "V-9", "date": "2026-10-01", "status": "Open",
             "doc_status": "Submitted", "total": "10", "lines": [line]}  # fmt: skip
    with pytest.raises(ValidationError, match="unknown vendor V-9"):
        SnapshotDocument.model_validate({**base, "purchase_orders": [order]})
    with pytest.raises(ValidationError, match="unknown item B"):
        SnapshotDocument.model_validate(
            {**base, "vendors": [{"id": "V-9", "name": "V", "status": "Active"}],
             "purchase_orders": [{**order, "lines": [{**order["lines"][0], "item_code": "B"}]}]}
        )  # fmt: skip


def test_the_contract_refuses_dangling_receivables_links() -> None:
    base = {"provenance": "SYNTHETIC_DEMO", "company_id": "x", "company_name": "x",
            "entity": "US01", "currency": "USD", "basis": "Accrual", "as_of": "2026-11-03",
            "source_reference": "t", "items": [{"code": "A", "name": "A", "group": "G",
                                                 "stock_item": False}],
            "clients": [{"id": "C-1", "name": "C", "status": "Active"}]}  # fmt: skip
    invoice = {"id": "SI-1", "client_id": "C-9", "posting_date": "2026-10-01",
               "status": "Unpaid", "doc_status": "Submitted", "currency": "USD",
               "net_total": "10", "total": "10", "outstanding": "10",
               "lines": [{"item_code": "A", "qty": "1", "rate": "10", "amount": "10"}]}  # fmt: skip
    with pytest.raises(ValidationError, match="unknown client C-9"):
        SnapshotDocument.model_validate({**base, "sales_invoices": [invoice]})
    payment = {"id": "PE-1", "client_id": "C-1", "date": "2026-10-02", "amount": "5",
               "allocations": [{"invoice_id": "SI-9", "amount": "5"}]}  # fmt: skip
    with pytest.raises(ValidationError, match="unknown SI-9"):
        SnapshotDocument.model_validate(
            {**base, "sales_invoices": [{**invoice, "client_id": "C-1"}],
             "client_payments": [payment]}
        )  # fmt: skip


def test_service_pod_exports_keep_their_digest() -> None:
    doc = SnapshotDocument.model_validate(snapshot_payload())
    payload = stored_payload(doc)
    assert "vendors" not in payload and "bills" not in payload
    assert "customers" in payload


# --- posting -----------------------------------------------------------------------------


@pytest.fixture
def service_flow(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A Service POD workflow with no steps and no required data, so a case on an ERPNext
    snapshot can be approved and its posting task proposed through the /pod endpoints."""
    spec = replace(DEMO_SPEC, pod=PodKey.SERVICE, plan=StepPlan(), signoffs=("Finance Admin",),
                   signoff_sod=False)  # fmt: skip
    monkeypatch.setitem(WORKFLOWS, DEMO_KEY, spec)
    if DEMO_KEY in HOOKS:
        monkeypatch.delitem(HOOKS, DEMO_KEY)
    yield


async def _approved_case(admin: AsyncClient, snap: dict[str, Any]) -> dict[str, Any]:
    r = await admin.post(
        "/api/v1/pod/cases",
        json={"workflow": DEMO_KEY.value, "snapshot_id": snap["id"], "title": "Onboard vendor"},
    )
    assert r.status_code == 201, r.text
    case = r.json()
    r = await admin.post(
        f"/api/v1/pod/cases/{case['id']}/actions",
        json={"action": "approve", "expected_version": case["version"], "payload": {}},
    )
    assert r.status_code == 200, r.text
    approved: dict[str, Any] = r.json()
    return approved


async def _task_action(admin: AsyncClient, task: dict[str, Any], action: str, **body: Any) -> Any:
    return await admin.post(
        f"/api/v1/pod/tasks/{task['id']}/actions",
        json={"action": action, "expected_version": task["version"], **body},
    )


async def test_the_app_posts_once_and_a_fresh_snapshot_verifies_it(
    admin: AsyncClient, erp: FakeErpNext, entity: LegalEntity, service_flow: None
) -> None:
    source = (await _connect(admin)).json()
    snap = (await _snapshot(admin, source, entity)).json()["snapshot"]
    case = await _approved_case(admin, snap)
    r = await admin.post(
        f"/api/v1/pod/cases/{case['id']}/tasks",
        json={"kind": "create_supplier", "reference": "Nova Gem Tools",
              "instructions": {"doc": {"supplier_name": "Nova Gem Tools",
                                       "supplier_group": "Lab Suppliers"}}},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["allowed_actions"]["record"] == "The app posts this to the ERP: use post."

    erp.fail_after_insert = True  # created in ERPNext, but the answer is lost
    r = await _task_action(admin, task, "post")
    assert r.status_code == 409
    assert "Retrying is safe" in r.json()["detail"]["message"]
    r = await _task_action(admin, task, "post")
    assert r.status_code == 200, r.text
    task = r.json()
    assert (task["status"], task["external_txn_id"]) == ("recorded_unverified", "Nova Gem Tools")
    assert len(erp.inserted) == 1  # the retry found the first attempt's supplier
    assert erp.inserted[0]["finance_acc_ref"]

    r = await _task_action(admin, task, "verify", snapshot_id=snap["id"])
    assert r.status_code == 409  # the case's own snapshot proves nothing
    fresh = (await _snapshot(admin, source, entity)).json()
    assert fresh["created"] is True  # the new supplier changed the data
    r = await _task_action(admin, task, "verify", snapshot_id=fresh["snapshot"]["id"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
    assert r.json()["verification"]["posted_by_app"] is True


async def test_a_purchase_order_is_submitted_after_it_is_created(
    admin: AsyncClient, erp: FakeErpNext, entity: LegalEntity, service_flow: None
) -> None:
    source = (await _connect(admin)).json()
    snap = (await _snapshot(admin, source, entity)).json()["snapshot"]
    case = await _approved_case(admin, snap)
    doc = {"supplier": "LabChem Supply Co", "company": COMPANY, "transaction_date": "2026-11-03",
           "items": [{"item_code": "LC-PASTE", "qty": 40, "rate": 38,
                      "schedule_date": "2026-11-20"}]}  # fmt: skip
    task = (
        await admin.post(
            f"/api/v1/pod/cases/{case['id']}/tasks",
            json={
                "kind": "create_purchase_order",
                "reference": "MR-1",
                "instructions": {"doc": doc},
            },
        )
    ).json()
    r = await _task_action(admin, task, "post")
    assert r.status_code == 200, r.text
    name = r.json()["external_txn_id"]
    assert erp.submitted == [("Purchase Order", name)]
    assert erp.docs["Purchase Order"][name]["docstatus"] == 1


async def test_a_case_not_read_from_erpnext_cannot_post(
    admin: AsyncClient, erp: FakeErpNext, entity: LegalEntity, service_flow: None
) -> None:
    from tests.service_pod.conftest import import_snapshot

    snap = (await import_snapshot(admin, entity)).json()["snapshot"]  # a JSON export
    case = await _approved_case(admin, snap)
    task = (
        await admin.post(
            f"/api/v1/pod/cases/{case['id']}/tasks",
            json={
                "kind": "create_supplier",
                "reference": "X",
                "instructions": {"doc": {"supplier_name": "X"}},
            },
        )
    ).json()
    r = await _task_action(admin, task, "post")
    assert r.status_code == 409
    assert "wasn't read from a connected ERPNext" in r.json()["detail"]["message"]
    assert erp.inserted == []


def test_dates_stay_dates() -> None:
    from src.app.service_pod.core.snapshots.importers.erpnext import _date

    assert _date("2026-11-03 10:00:00") == date(2026, 11, 3)
    assert _date(None) is None
