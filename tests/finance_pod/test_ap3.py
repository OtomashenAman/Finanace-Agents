"""AP-3 Invoice Processing & Matching, end to end on a fictional snapshot "read from" a
stand-in ERPNext: a clean match, a price variance, a short receipt, a missing receipt, a
duplicate, a non-PO invoice and a credit note. Each rule is proved by a marked test."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.common.clock import utcnow
from src.app.finance_pod.flows.ap_invoice_match import service as apm
from src.app.service_pod.core.cases.models import PodCase, PodReviewTask
from src.app.service_pod.core.snapshots.models import PodSnapshotSource
from tests.finance_pod.ap_data import AP3_BILLS, AP3_RECEIPTS, LC, ap3_payload
from tests.finance_pod.conftest import Cap, PersonFn, World, step
from tests.finance_pod.fake_erpnext import FakeErpNext
from tests.finance_pod.test_ap1 import act, ok, run
from tests.service_pod.conftest import import_snapshot

APM = "ap_invoice_match"


async def take(w: World, db: AsyncSession, **changes: Any) -> dict[str, Any]:
    assert w.admin and w.entity and w.source
    r = await import_snapshot(
        w.admin, w.entity, ap3_payload(source_reference=f"read {uuid.uuid4()}", **changes)
    )
    assert r.status_code in (200, 201), r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    db.add(PodSnapshotSource(snapshot_id=uuid.UUID(snap["id"]), data_source_id=w.source.id))
    await db.commit()
    return snap


async def invoice_case(w: World, snap: dict[str, Any], bill_id: str) -> dict[str, Any]:
    r = await w["analyst"].post(
        "/api/v1/finance/cases",
        json={
            "workflow": APM,
            "snapshot_id": snap["id"],
            "title": bill_id,
            "selection": {"bill_id": bill_id},
        },
    )
    assert r.status_code == 201, r.text
    case: dict[str, Any] = r.json()
    up = await w["analyst"].post(
        f"/api/v1/finance/cases/{case['id']}/artifacts",
        files={"file": (f"{bill_id}.txt", f"Invoice {bill_id}".encode(), "text/plain")},
        data={"kind": "invoice_copy"},
    )
    assert up.status_code == 201, up.text
    return case


async def to_classified(w: World, snap: dict[str, Any], bill_id: str) -> dict[str, Any]:
    case = await invoice_case(w, snap, bill_id)
    for key in ("3.2.1", "3.2.2", "3.4.1", "3.4.2"):
        case = await run(w["analyst"], case, key)
    return case


def route(case: dict[str, Any]) -> str:
    result: str = step(case, "3.4.2")["l5"][0]["result"]["route"]
    return result


def lines(case: dict[str, Any], key: str = "3.4.1") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = step(case, key)["l5"][0]["result"]["lines"]
    return found


@pytest.mark.requirement("AP3.R1", "AP3.P1")
async def test_a_clean_invoice_goes_to_coding(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    case = await invoice_case(w, snap, "BILL-OK")
    case = await run(w["analyst"], case, "3.2.1")
    record = step(case, "3.2.1")["l5"][0]["result"]
    assert (record["erp_invoice"], record["po_backed"]) == ("BILL-OK", True)  # nothing re-keyed
    for key in ("3.2.2", "3.4.1", "3.4.2"):
        case = await run(w["analyst"], case, key)
    assert lines(case)[0]["status"] == "match"  # +1.3% is within the 2% line tolerance
    assert lines(case)[0]["price_variance_pct"] == "1.32"
    assert route(case) == "coding"
    for key in ("3.5.1", "3.5.2", "3.6.1", "3.6.2", "3.5.3"):
        assert step(case, key)["status"] == "not_applicable", key
    assert case["status"] == "approved"  # released to coding (AP-4)
    tiles = (await w["analyst"].get("/api/v1/finance/dashboard")).json()["workflows"]
    rate = next(m for t in tiles if t["key"] == APM for m in t["measures"] if m["id"] == "AP3.M1")
    assert rate["value"] == "100.0"


async def test_an_invoice_needs_its_source_document(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    r = await w["analyst"].post(
        "/api/v1/finance/cases",
        json={
            "workflow": APM,
            "snapshot_id": snap["id"],
            "title": "x",
            "selection": {"bill_id": "BILL-OK"},
        },
    )
    case = await run(w["analyst"], r.json(), "3.2.1")
    assert "attach the vendor's invoice document" in step(case, "3.2.1")["l5"][0]["note"]
    again = await w["analyst"].post(
        "/api/v1/finance/cases",
        json={
            "workflow": APM,
            "snapshot_id": snap["id"],
            "title": "x",
            "selection": {"bill_id": "BILL-OK"},
        },
    )
    assert again.status_code == 422 and "already has a matching case" in again.text


@pytest.mark.requirement("AP3.R1", "AP3.G1", "AP3.G2", "AP3.P2")
async def test_a_price_variance_goes_to_the_buyer(
    world: World, db: AsyncSession, erp: FakeErpNext, person: PersonFn
) -> None:
    w = world
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-PRICE")
    assert lines(case)[0]["status"] == "price" and route(case) == "exception"
    assert "+9.17%" in lines(case)[0]["reason"]
    assert step(case, "3.6.1")["status"] == "not_applicable"  # received in full
    case = await run(w["buyer"], case, "3.5.1")
    view = step(case, "3.5.1")["l5"][0]["result"]["rows"][0]
    assert (view["po_rate"], view["billed_rate"], view["received"]) == ("12", "13.1", "50")
    query = next(m for m in case["messages"] if m["purpose"] == "invoice_query")
    assert query["to_email"] == "orders@labchem.example.com" and query["status"] == "draft"

    r = await act(
        w["analyst"],
        case,
        "complete_step",
        step="3.5.2",
        results={"3.5.2.a": {"decision": "accept", "note": "agreed"}},
    )
    assert r.status_code == 409  # the buyer decides
    case = await ok(
        w["buyer"],
        case,
        "complete_step",
        step="3.5.2",
        results={"3.5.2.a": {"decision": "accept", "note": "Price rise agreed by phone"}},
    )
    case = await run(w["buyer"], case, "3.5.3")
    closed = step(case, "3.5.3")["l5"][0]["result"]
    assert closed["released"] is True and "accepted by the buyer" in closed["how"]
    assert case["status"] == "approved"
    assert erp.inserted == []  # AP3.G1: no PO (nor anything) written by an agent
    events = list(
        await db.scalars(
            select(AuditEvent.details["summary"].astext).where(
                AuditEvent.details["case_id"].astext == case["id"]
            )
        )
    )
    assert any("3.5.2 Buyer decides: done" in (e or "") for e in events)  # AP3.G2
    tiles = (await w["buyer"].get("/api/v1/finance/dashboard")).json()["workflows"]
    measures = {m["id"]: m["value"] for t in tiles if t["key"] == APM for m in t["measures"]}
    assert measures["AP3.M1"] == "0.0"


async def test_a_short_delivery_is_settled_by_a_credit(
    world: World, db: AsyncSession, erp: FakeErpNext, person: PersonFn
) -> None:
    """Billed in full, part never comes: the receiver says so, the buyer asks for a credit."""
    w = world
    _, receiver = await person("rcv@example.com", Cap.RECEIVER)
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-QTY")
    case = await run(w["buyer"], case, "3.5.1")
    case = await ok(
        w["buyer"],
        case,
        "complete_step",
        step="3.5.2",
        results={"3.5.2.a": {"decision": "credit", "note": "Short", "expected_credit": "140"}},
    )
    case = await run(w["buyer"], case, "3.6.1")
    line = {"order_line_id": "PO-QTY-l1", "item_code": "LC-GLOVES", "received_qty": "0"}
    r = await act(
        receiver,
        case,
        "complete_step",
        step="3.6.2",
        results={"3.6.2.a": {"received_on": utcnow().date().isoformat(), "lines": [line]}},
    )
    assert r.status_code == 409 and "mark the lines short" in r.json()["detail"]["message"]
    case = await ok(
        receiver,
        case,
        "complete_step",
        step="3.6.2",
        results={
            "3.6.2.a": {
                "received_on": utcnow().date().isoformat(),
                "lines": [{**line, "condition": "short"}],
            }
        },
    )
    assert step(case, "3.6.2")["status"] == "done" and case["posting_tasks"] == []
    assert erp.inserted == []
    case = await run(w["buyer"], case, "3.5.3")
    assert "Waiting for the vendor's credit note" in step(case, "3.5.3")["l5"][0]["note"]


async def test_a_short_receipt_waits_for_the_receiver(
    world: World, db: AsyncSession, erp: FakeErpNext, person: PersonFn
) -> None:
    w = world
    _, receiver = await person("rcv@example.com", Cap.RECEIVER)
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-QTY")
    assert lines(case)[0]["status"] == "quantity" and lines(case)[0]["quantity_over"] == "10"
    case = await run(w["buyer"], case, "3.5.1")
    case = await ok(
        w["buyer"],
        case,
        "complete_step",
        step="3.5.2",
        results={"3.5.2.a": {"decision": "accept", "note": "rest arrived"}},
    )
    case = await run(w["buyer"], case, "3.6.1")
    assert step(case, "3.6.1")["l5"][0]["result"]["receivers"] == ["Rcv"]
    queue = (await receiver.get("/api/v1/finance/dashboard")).json()["my_queue"]
    assert [(q["reference"], q["step_key"]) for q in queue] == [(case["reference"], "3.6.2")]

    case = await ok(
        receiver,
        case,
        "complete_step",
        step="3.6.2",
        results={
            "3.6.2.a": {
                "received_on": utcnow().date().isoformat(),
                "lines": [
                    {"order_line_id": "PO-QTY-l1", "item_code": "LC-GLOVES", "received_qty": "10"}
                ],
            }
        },
    )
    receipt = erp.inserted[-1]
    assert "posting_date" not in receipt  # today's receipt takes ERPNext's own today
    assert (receipt["doctype"], receipt["items"][0]["purchase_order_item"]) == (
        "Purchase Receipt",
        "PO-QTY-l1",
    )
    task = case["posting_tasks"][0]
    assert (task["kind"], task["status"]) == ("create_purchase_receipt", "recorded_unverified")
    case = await run(w["buyer"], case, "3.5.3")
    assert "verify it with a fresh snapshot" in step(case, "3.5.3")["l5"][0]["note"]

    fresh = await take(
        w,
        db,
        purchase_receipts=[
            *AP3_RECEIPTS,
            {
                "id": receipt["name"],
                "vendor_id": "GemTech Instruments",
                "date": "2026-11-03",
                "status": "To Bill",
                "doc_status": "Submitted",
                "lines": [
                    {
                        "id": "new-l1",
                        "item_code": "LC-GLOVES",
                        "qty": "10",
                        "rate": "14",
                        "order_id": "PO-QTY",
                        "order_line_id": "PO-QTY-l1",
                    }
                ],
            },
        ],
    )
    r = await w["analyst"].post(
        f"/api/v1/finance/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": fresh["id"]},
    )
    assert r.status_code == 200, r.text
    case = await ok(w["buyer"], case, "refresh_source", snapshot_id=fresh["id"])
    case = await run(w["buyer"], case, "3.5.3")
    closed = step(case, "3.5.3")["l5"][0]["result"]
    assert closed["lines"][0]["status"] == "match" and closed["how"] == "every line matches now"
    assert case["status"] == "approved"
    case = await ok(w["analyst"], case, "complete")
    assert case["status"] == "completed"


async def test_nothing_received_goes_to_the_receiver(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-NONE")
    assert lines(case)[0]["status"] == "no_receipt"
    assert step(case, "3.5.1")["status"] == "not_applicable"  # no price / quantity variance
    assert step(case, "3.5.2")["status"] == "not_applicable"
    case = await run(w["analyst"], case, "3.6.1")
    assert step(case, "3.6.1")["l5"][0]["result"]["lines"] == ["LC-GLOVES (PO-NONE)"]


@pytest.mark.requirement("AP3.R2")
async def test_a_duplicate_is_blocked_and_explained(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    case = await invoice_case(w, snap, "BILL-DUP")
    case = await run(w["analyst"], case, "3.2.1")
    case = await run(w["analyst"], case, "3.2.2")
    decision = step(case, "3.2.2")["l5"][1]["result"]
    assert decision["blocked"] is True and "BILL-POSTED" in decision["explanation"]
    found = step(case, "3.2.2")["l5"][0]["result"]["matches"]
    assert [m["bill_id"] for m in found] == ["BILL-POSTED"]
    assert any("duplicate blocks this invoice (AP3.R2)" in b for b in case["blockers"])
    review = next(t for t in case["review_tasks"] if t["subject"] == "Possible duplicate")
    assert review["blocking"] is True
    # It goes no further: matching would route it to coding
    case = await run(w["analyst"], case, "3.4.1")
    assert step(case, "3.4.1")["status"] == "failed"
    assert step(case, "3.4.2")["status"] == "pending"
    tiles = (await w["analyst"].get("/api/v1/finance/dashboard")).json()["workflows"]
    stopped = next(
        m for t in tiles if t["key"] == APM for m in t["measures"] if m["id"] == "AP3.M3"
    )
    assert stopped["value"] == "1"
    case = await ok(w["analyst"], case, "cancel", reason="Duplicate of LC-INV-4502, already paid")
    assert case["status"] == "cancelled"


async def test_a_non_po_invoice_goes_to_coding(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-NOPO")
    assert lines(case)[0]["status"] == "no_po" and route(case) == "coding_non_po"
    assert case["status"] == "approved"


async def test_a_credit_note_closes_a_price_variance(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-PRICE")
    case = await run(w["buyer"], case, "3.5.1")
    case = await ok(
        w["buyer"],
        case,
        "complete_step",
        step="3.5.2",
        results={
            "3.5.2.a": {"decision": "credit", "note": "Vendor agreed", "expected_credit": "55"}
        },
    )
    case = await run(w["buyer"], case, "3.5.3")
    assert "Waiting for the vendor's credit note" in step(case, "3.5.3")["l5"][0]["note"]
    credit = {
        "id": "CN-1",
        "vendor_id": LC,
        "bill_number": "LC-5002-CN",
        "bill_date": "2026-11-02",
        "posting_date": "2026-11-02",
        "status": "Return",
        "doc_status": "Submitted",
        "total": "-55",
        "outstanding": "-55",
        "return_against": "BILL-PRICE",
        "lines": [{"item_code": "LC-PASTE", "qty": "-50", "rate": "1.10", "amount": "-55"}],
    }
    fresh = await take(w, db, bills=[*AP3_BILLS, credit])
    case = await ok(w["buyer"], case, "refresh_source", snapshot_id=fresh["id"])
    case = await run(w["buyer"], case, "3.5.3")
    assert "credit note of 55" in step(case, "3.5.3")["l5"][0]["result"]["how"]
    assert case["status"] == "approved"


@pytest.mark.requirement("AP3.P1")
async def test_intake_opens_a_case_for_every_incoming_invoice(
    world: World, db: AsyncSession
) -> None:
    w = world
    snap = await take(w, db)
    r = await w["analyst"].post("/api/v1/finance/apm/intake", json={"snapshot_id": snap["id"]})
    assert r.status_code == 200, r.text
    assert len(r.json()["opened"]) == 6  # the drafts; the posted one isn't incoming
    again = await w["analyst"].post("/api/v1/finance/apm/intake", json={"snapshot_id": snap["id"]})
    assert again.json() == {"opened": [], "already": 6}
    assert (
        await w["buyer"].post("/api/v1/finance/apm/intake", json={"snapshot_id": snap["id"]})
    ).status_code == 403


@pytest.mark.requirement("AP3.R3", "AP3.P3")
async def test_held_invoices_are_reviewed_weekly(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    case = await to_classified(w, snap, "BILL-PRICE")
    await db.execute(
        update(PodCase)
        .where(PodCase.id == uuid.UUID(case["id"]))
        .values(updated_at=utcnow() - timedelta(days=8))
    )
    await db.commit()
    await apm.review_held(db, {}, None)  # type: ignore[arg-type]
    await db.commit()
    subjects = list(
        await db.scalars(
            select(PodReviewTask.subject).where(PodReviewTask.case_id == uuid.UUID(case["id"]))
        )
    )
    assert subjects == ["Weekly review"]
    tiles = (await w["analyst"].get("/api/v1/finance/dashboard")).json()["workflows"]
    ageing = next(m for t in tiles if t["key"] == APM for m in t["measures"] if m["id"] == "AP3.M2")
    assert ageing["value"] is not None


async def test_the_analyst_picks_an_incoming_invoice(world: World, db: AsyncSession) -> None:
    """The New case form lists the ERPNext drafts a matching case can start from."""
    w = world
    snap = await take(w, db)
    r = await w["analyst"].get(f"/api/v1/finance/sources/{snap['id']}/catalogue?workflow={APM}")
    assert r.status_code == 200, r.text
    listed = {b["id"] for b in r.json()["incoming_invoices"]}
    assert "BILL-DUP" in listed and "BILL-POSTED" not in listed  # drafts only
    await invoice_case(w, snap, "BILL-DUP")
    r = await w["analyst"].get(f"/api/v1/finance/sources/{snap['id']}/catalogue?workflow={APM}")
    assert "BILL-DUP" not in {b["id"] for b in r.json()["incoming_invoices"]}  # has a case now
