"""AR-3 Billing & Invoicing: a case per lab submission whose report is issued, priced by the
schedule, a client's price or a contract discount, taxed by location, checked against the
fee estimate, settled by a billing analyst when flagged, posted to a stand-in ERPNext, emailed
and put on the month's statement. Each rule, guardrail and pain point is proved by a test."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.service_pod.core.snapshots.models import PodSnapshotSource
from tests.finance_pod.ap_data import AP_SNAPSHOT, ap_payload
from tests.finance_pod.conftest import Cap, PersonFn, World, step
from tests.finance_pod.fake_erpnext import FakeErpNext
from tests.finance_pod.test_ap1 import act, ok, run
from tests.service_pod.conftest import import_snapshot

BIL = "ar_billing"
CHECKS = {"recipient": True, "mapping": True, "tone": True}
SERVICES = [
    {"code": code, "name": name, "group": "Lab Services", "stock_item": False}
    for code, name in (("GR-DIA", "Diamond Grading Report"), ("GR-DOS", "Diamond Dossier"),
                       ("SV-LASER", "Laser inscription"), ("SV-NEW", "New service"))
]  # fmt: skip
CLIENTS = [
    {"id": "Brilliant", "name": "Brilliant Gems LLC", "email": "ap@brilliant.example.com",
     "status": "Active", "terms_days": 30, "credit_limit": "50000",
     "tax_category": "Domestic"},
    {"id": "Rivera", "name": "Rivera Fine Jewelry", "email": "ap@rivera.example.com",
     "status": "Active", "terms_days": 30, "tax_category": "Domestic"},
    {"id": "Antwerp", "name": "Antwerp Diamond House", "email": "fin@antwerp.example.com",
     "status": "Active", "terms_days": 45, "tax_category": "Export"},
]  # fmt: skip


def _sub(sub_id: str, client: str, lines: list[tuple[str, str, str, bool]], estimate: str,
         issued: str | None = "2026-10-30", billed: bool = False) -> dict[str, Any]:  # fmt: skip
    rows = []
    for n, (code, qty, rate, added) in enumerate(lines, 1):
        amount = str(float(qty) * float(rate))
        rows.append({"id": f"{sub_id}-l{n}", "item_code": code, "qty": qty, "rate": rate,
                     "amount": amount, "added": added,
                     "billed_amount": amount if billed else "0"})  # fmt: skip
    total = str(sum(float(r["amount"]) for r in rows))
    return {"id": sub_id, "client_id": client, "date": "2026-10-26", "status": "To Bill",
            "doc_status": "Submitted", "total": total, "fee_estimate": estimate,
            "report_issued_on": issued, "lines": rows}  # fmt: skip


SUBMISSIONS = [
    _sub("SO-BR", "Brilliant", [("GR-DIA", "10", "150", False)], "1500"),
    _sub("SO-RV", "Rivera", [("GR-DOS", "5", "90", False), ("SV-LASER", "5", "40", True)], "450"),
    _sub("SO-AN", "Antwerp", [("GR-DOS", "3", "90", False)], "270"),
    _sub("SO-NEW", "Rivera", [("SV-NEW", "1", "80", False)], "80"),
    _sub("SO-INLAB", "Brilliant", [("GR-DIA", "2", "150", False)], "300", issued=None),
    _sub("SO-OLD", "Brilliant", [("GR-DIA", "1", "150", False)], "150", billed=True),
]
AR3 = {
    "items": [*AP_SNAPSHOT["items"], *SERVICES],
    "clients": CLIENTS,
    "submissions": SUBMISSIONS,
    "selling_prices": [
        {"item_code": "GR-DIA", "rate": "150", "currency": "USD"},
        {"item_code": "GR-DOS", "rate": "90", "currency": "USD"},
        {"item_code": "SV-LASER", "rate": "40", "currency": "USD"},
    ],
    "price_rules": [
        {"id": "PR-1", "item_group": "Lab Services", "client_id": "Brilliant",
         "discount_pct": "10", "valid_from": "2026-01-01"},
    ],
    "tax_rules": [
        {"id": "US ST 6.25%", "tax_category": "Domestic", "rate_pct": "6.25",
         "account_id": "ST - GIAD", "default": True},
        {"id": "Export 0%", "tax_category": "Export", "rate_pct": "0", "account_id": "ST - GIAD"},
    ],
    "sales_invoices": [],
}  # fmt: skip


async def take(w: World, db: AsyncSession, **changes: Any) -> dict[str, Any]:
    assert w.admin and w.entity and w.source
    data = {**AR3, **changes}
    payload = ap_payload(source_reference=f"read {uuid.uuid4()}", **data)
    r = await import_snapshot(w.admin, w.entity, payload)
    assert r.status_code in (200, 201), r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    db.add(PodSnapshotSource(snapshot_id=uuid.UUID(snap["id"]), data_source_id=w.source.id))
    await db.commit()
    return snap


@pytest.fixture
async def desk(world: World, person: PersonFn) -> World:
    world.users["billing"], world.clients["billing"] = await person(
        "billing@example.com", Cap.BILLING_ANALYST
    )
    world.users["credit"], world.clients["credit"] = await person(
        "credit@example.com", Cap.CREDIT_CONTROLLER
    )
    return world


async def taken_in(w: World, snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    r = await w["billing"].post("/api/v1/finance/arb/intake", json={"snapshot_id": snap["id"]})
    assert r.status_code == 200, r.text
    cases = (await w["billing"].get("/api/v1/finance/cases")).json()
    return {c["title"].split(" · ")[-1]: c for c in cases if c["workflow"] == BIL}


async def priced(w: World, case: dict[str, Any]) -> dict[str, Any]:
    for key in ("3.1.1", "3.1.2", "3.2.1", "3.2.2"):
        case = await run(w["billing"], case, key)
        assert step(case, key)["status"] == "done", step(case, key)
    return case


async def send_drafts(client: AsyncClient, case: dict[str, Any], purpose: str) -> int:
    fresh = (await client.get(f"/api/v1/finance/cases/{case['id']}")).json()
    n = 0
    for m in fresh["messages"]:
        if m["purpose"] == purpose and m["status"] == "draft":
            body = {"expected_version": m["version"], "checks": CHECKS}
            r = await client.post(f"/api/v1/finance/messages/{m['id']}/send", json=body)
            assert r.status_code == 200, r.text
            n += 1
    return n


def posted_row(doc: dict[str, Any], client: str, total: str, tax: str) -> dict[str, Any]:
    return {"id": doc["name"], "client_id": client, "posting_date": "2026-11-03",
            "due_date": "2026-12-03", "status": "Unpaid", "doc_status": "Submitted",
            "currency": "USD", "net_total": str(float(total) - float(tax)), "tax_total": tax,
            "total": total, "outstanding": total, "lines": []}  # fmt: skip


@pytest.mark.requirement("AR3.R1")
async def test_every_completed_submission_is_taken_in_once(desk: World, db: AsyncSession) -> None:
    w = desk
    snap = await take(w, db)
    cases = await taken_in(w, snap)
    assert sorted(cases) == ["SO-AN", "SO-BR", "SO-NEW", "SO-RV"]  # in the lab / billed: not
    r = await w["billing"].post("/api/v1/finance/arb/intake", json={"snapshot_id": snap["id"]})
    assert r.json() == {"opened": [], "already": 4}
    r = await w["credit"].post("/api/v1/finance/arb/intake", json={"snapshot_id": snap["id"]})
    assert r.status_code == 403
    r = await w["billing"].post(
        "/api/v1/finance/cases",
        json={"workflow": BIL, "snapshot_id": snap["id"], "title": "x",
              "selection": {"submission_id": "SO-INLAB"}},
    )  # fmt: skip
    assert r.status_code == 422 and "isn't issued" in r.json()["detail"]["message"]


@pytest.mark.requirement("AR3.G1", "AR3.P1", "AR3.P3")
async def test_a_clean_invoice_goes_out_and_onto_the_statement(
    desk: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    w = desk
    snap = await take(w, db)
    case = await priced(w, (await taken_in(w, snap))["SO-BR"])
    line = step(case, "3.2.1")["l5"][0]["result"]["lines"][0]
    assert (line["rate"], line["source"], line["discount_pct"]) == ("135.00", "contract discount",
                                                                    "10")  # fmt: skip
    assert step(case, "3.2.2")["l5"][1]["result"]["flags"] == []
    assert step(case, "3.3.1")["status"] == "not_applicable"
    assert case["status"] == "approved"  # released: nothing to review

    # AR3.G1 / P1: only the invoice is posted, built from the submission's own lines
    assert [d["doctype"] for d in erp.inserted] == ["Sales Invoice"]
    invoice = erp.inserted[0]
    item = invoice["items"][0]
    assert (item["rate"], item["sales_order"], item["so_detail"]) == ("135.00", "SO-BR", "SO-BR-l1")
    assert invoice["taxes"][0]["rate"] == "6.25" and invoice["ignore_pricing_rule"] == 1
    assert erp.submitted == [("Sales Invoice", invoice["name"])]

    case = await run(w["billing"], case, "3.5.1.a")
    assert "verify it with a fresh snapshot" in step(case, "3.5.1.a")["l5"][0]["note"]
    fresh = await take(w, db, sales_invoices=[posted_row(invoice, "Brilliant", "1434.38", "84.38")])
    task = case["posting_tasks"][0]
    r = await w["billing"].post(
        f"/api/v1/finance/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": fresh["id"]},
    )
    assert r.status_code == 200, r.text
    case = await run(w["billing"], case, "3.5.1.a")
    assert "drafted" in step(case, "3.5.1.a")["l5"][0]["note"]
    assert await send_drafts(w["billing"], case, "client_invoice") == 1
    case = await run(w["billing"], case, "3.5.1.a")
    assert step(case, "3.5.1.a")["status"] == "done", step(case, "3.5.1.a")["l5"][0]["note"]

    # AR3.P3: the month's statements go out in one batch
    case = await run(w["billing"], case, "3.5.1.b")
    assert "statement" in step(case, "3.5.1.b")["l5"][0]["note"]
    r = await w["billing"].post("/api/v1/finance/arb/statements", json={"month": "2026-11"})
    assert r.status_code == 200 and r.json()["drafted"] == ["Brilliant"], r.text
    r = await w["credit"].post("/api/v1/finance/arb/statements/send", json={"month": "2026-11"})
    assert r.status_code == 403
    r = await w["billing"].post("/api/v1/finance/arb/statements/send", json={"month": "2026-11"})
    assert r.json()["sent"] == ["Brilliant Gems LLC"], r.text
    case = await run(w["billing"], case, "3.5.1.b")
    assert step(case, "3.5.1.b")["l5"][0]["result"]["statement_month"] == "2026-11"
    case = await ok(w["billing"], case, "complete")
    assert case["status"] == "completed"
    tiles = (await w["billing"].get("/api/v1/finance/dashboard")).json()["workflows"]
    measures = {m["id"]: m["value"] for t in tiles if t["key"] == BIL for m in t["measures"]}
    assert measures["AR3.M1"] == "100.00" and measures["AR3.M2"] is not None


@pytest.mark.requirement("AR3.P2")
async def test_an_added_service_is_flagged_and_settled_on_the_invoice(
    desk: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    w = desk
    snap = await take(w, db)
    case = await priced(w, (await taken_in(w, snap))["SO-RV"])
    flags = step(case, "3.2.2")["l5"][1]["result"]["flags"]
    assert any("SV-LASER was added in the lab" in f for f in flags)
    assert any("off the fee estimate" in f for f in flags)
    assert case["status"] == "draft" and erp.inserted == []
    review = {"3.3.1.a": {"reviewed": True, "note": "Client asked for inscriptions at intake"}}
    r = await act(w["credit"], case, "complete_step", step="3.3.1",
                  results={**review, "3.3.1.b": {"overrides": []}})  # fmt: skip
    assert r.status_code == 409  # a billing analyst's step
    r = await act(w["billing"], case, "complete_step", step="3.3.1", results={
        **review, "3.3.1.b": {"overrides": [{"item_code": "GR-DIA", "rate": "1", "reason": "x x"}]}
    })  # fmt: skip
    assert r.status_code == 409 and "Not on this invoice" in r.json()["detail"]["message"]
    agreed = {"overrides": [{"item_code": "SV-LASER", "rate": "30", "reason": "Agreed at intake"}]}
    case = await ok(w["billing"], case, "complete_step", step="3.3.1",
                    results={**review, "3.3.1.b": agreed})  # fmt: skip
    assert case["status"] == "approved"
    rates = {i["item_code"]: i["rate"] for i in erp.inserted[0]["items"]}
    assert rates == {"GR-DOS": "90.00", "SV-LASER": "30.00"}
    tiles = (await w["billing"].get("/api/v1/finance/dashboard")).json()["workflows"]
    accuracy = next(m for t in tiles if t["key"] == BIL for m in t["measures"]
                    if m["id"] == "AR3.M1")  # fmt: skip
    assert accuracy["value"] == "0.00"


@pytest.mark.requirement("AR3.R3")
async def test_an_export_client_is_zero_rated(
    desk: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    w = desk
    snap = await take(w, db)
    case = await priced(w, (await taken_in(w, snap))["SO-AN"])
    taxed = step(case, "3.2.1")["l5"][1]["result"]
    assert (taxed["tax_rule"], taxed["rate_pct"], taxed["tax"], taxed["total"]) == (
        "Export 0%", "0", "0.00", "270.00",
    )  # fmt: skip
    assert erp.inserted[0]["taxes_and_charges"] == "Export 0%"


@pytest.mark.requirement("AR3.R2")
async def test_a_service_without_a_fee_needs_a_billing_analyst(
    desk: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    w = desk
    snap = await take(w, db)
    case = await priced(w, (await taken_in(w, snap))["SO-NEW"])
    assert step(case, "3.2.1")["l5"][0]["result"]["lines"][0]["source"] == "no fee"
    review = {"3.3.1.a": {"reviewed": True, "note": "New service, not on the schedule yet"}}
    case = await ok(w["billing"], case, "complete_step", step="3.3.1",
                    results={**review, "3.3.1.b": {"overrides": []}})  # fmt: skip
    assert case["status"] == "draft"
    assert any("AR3.R2" in b for b in case["blockers"])
    case = await ok(w["billing"], case, "redo_step", step="3.3.1", reason="Set the fee")
    fee = {"overrides": [{"item_code": "SV-NEW", "rate": "80", "reason": "Quoted at intake"}]}
    case = await ok(w["billing"], case, "complete_step", step="3.3.1",
                    results={**review, "3.3.1.b": fee})  # fmt: skip
    assert case["status"] == "approved" and erp.inserted[0]["items"][0]["rate"] == "80.00"
