"""AP-1 Purchase Request & PO and Vendor Onboarding, end to end, on a fictional snapshot
"read from" a stand-in ERPNext (fake_erpnext.py). Each business rule, guardrail and pain
point of the requirement is proved by a test marked with its id."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.common.clock import utcnow
from src.app.finance_pod import sanctions
from src.app.finance_pod.flows.ap_vendor_onboarding import service as vnd_service
from src.app.service_pod.core.cases.models import PodCase, PodReviewTask
from src.app.service_pod.core.messaging.models import Direction, MessageStatus, PodMessage
from src.app.service_pod.core.snapshots.models import PodSnapshotSource
from tests.finance_pod.ap_data import (
    BANK_LETTER,
    CC,
    GRANT,
    LAB,
    OLD_GRANT,
    SDN_CSV,
    W9,
    ap_payload,
)
from tests.finance_pod.conftest import Cap, PersonFn, World, step
from tests.finance_pod.fake_erpnext import FakeErpNext
from tests.service_pod.conftest import import_snapshot

PRQ, VND = "ap_purchase_request", "ap_vendor_onboarding"
CHECKS = {"recipient": True, "mapping": True, "tone": True}
TODAY = utcnow().date()


async def take_snapshot(w: World, db: AsyncSession, **changes: Any) -> dict[str, Any]:
    """A snapshot of the ERPNext company (a JSON export linked to the ERPNext connection)."""
    assert w.admin and w.entity and w.source
    payload = ap_payload(source_reference=f"read {utcnow().isoformat()}", **changes)
    r = await import_snapshot(w.admin, w.entity, payload)
    assert r.status_code in (200, 201), r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    import uuid

    db.add(PodSnapshotSource(snapshot_id=uuid.UUID(snap["id"]), data_source_id=w.source.id))
    await db.commit()
    return snap


async def opened(
    client: AsyncClient,
    snap: dict[str, Any],
    workflow: str = PRQ,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    r = await client.post(
        "/api/v1/finance/cases",
        json={
            "workflow": workflow,
            "snapshot_id": snap["id"],
            "title": "Lab supplies",
            "selection": selection or {},
        },
    )
    assert r.status_code == 201, r.text
    case: dict[str, Any] = r.json()
    return case


async def act(client: AsyncClient, case: dict[str, Any], action: str, **payload: Any) -> Any:
    fresh = (await client.get(f"/api/v1/finance/cases/{case['id']}")).json()
    return await client.post(
        f"/api/v1/finance/cases/{case['id']}/actions",
        json={"action": action, "expected_version": fresh["version"], "payload": payload},
    )


async def ok(
    client: AsyncClient, case: dict[str, Any], action: str, **payload: Any
) -> dict[str, Any]:
    r = await act(client, case, action, **payload)
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


async def run(client: AsyncClient, case: dict[str, Any], key: str) -> dict[str, Any]:
    return await ok(client, case, "run_agent_step", step=key)


def need(lines: list[tuple[str, str]], **changes: Any) -> dict[str, Any]:
    return {
        "1.1.1.a": {
            "channel": "form",
            "purpose": "Research consumables",
            "needed_by": (TODAY + timedelta(days=14)).isoformat(),
            "lines": [{"item_code": c, "quantity": q} for c, q in lines],
            "cost_centre_id": CC,
            "lab_id": LAB,
            **changes,
        },
        "1.1.1.b": {"none_available": True},
    }


async def send_drafts(client: AsyncClient, case: dict[str, Any], purpose: str) -> int:
    fresh = (await client.get(f"/api/v1/finance/cases/{case['id']}")).json()
    sent = 0
    for m in fresh["messages"]:
        if m["purpose"] == purpose and m["status"] == "draft":
            r = await client.post(
                f"/api/v1/finance/messages/{m['id']}/send",
                json={"expected_version": m["version"], "checks": CHECKS},
            )
            assert r.status_code == 200, r.text
            sent += 1
    return sent


async def to_budget_owner(
    w: World, snap: dict[str, Any], lines: list[tuple[str, str]], **changes: Any
) -> dict[str, Any]:
    case = await opened(w["req"], snap)
    case = await ok(w["req"], case, "complete_step", step="1.1.1", results=need(lines, **changes))
    case = await run(w["req"], case, "1.1.2")
    return await run(w["req"], case, "1.2.1")


# --- the purchase request ------------------------------------------------------------------


@pytest.mark.requirement("AP1.R2", "AP1.P4")
async def test_a_small_request_goes_from_need_to_po(
    world: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await to_budget_owner(w, snap, [("LC-PASTE", "40")], grant_id=GRANT)
    assert step(case, "1.1.2")["status"] == "done"
    priced = step(case, "1.1.2")["l5"][1]["result"]
    assert (priced["total"], priced["lines"][0]["rate_source"]) == ("1520.00", "contract")
    budget = step(case, "1.2.1")["l5"][0]["result"]
    cc_line = next(ln for ln in budget["lines"] if ln["against"] == "cost_centre")
    # 5,000 budget - 1,200 actual - 800 open PO - 1,520 this request
    assert (cc_line["committed"], cc_line["remaining_after"]) == ("800.00", "1480.00")
    assert step(case, "1.2.1")["l5"][2]["result"]["quotes_required"] is False

    # AP1.R2: the requester can't take the budget owner's decision
    r = await act(
        w["req"],
        case,
        "complete_step",
        step="1.2.2",
        results={"1.2.2.a": {"reviewed": True}, "1.2.2.b": {"decision": "approve"}},
    )
    assert r.status_code == 409
    # AP1.P4: the requester sees where their request is and who it waits on
    mine = (await w["req"].get("/api/v1/finance/cases")).json()
    assert [(c["reference"], c["stage"]) for c in mine] == [(case["reference"], "1.2.2")]
    assert (mine[0]["next_title"], mine[0]["next_who"], mine[0]["next_failed"]) == (
        "Budget owner decides",
        "budget_owner",
        False,
    )
    assert step(case, "1.2.2")["capacity"] == "budget_owner"

    case = await ok(
        w["bo"],
        case,
        "complete_step",
        step="1.2.2",
        results={"1.2.2.a": {"reviewed": True}, "1.2.2.b": {"decision": "approve"}},
    )
    case = await run(w["buyer"], case, "1.3.1.a")
    assert step(case, "1.3.1.b")["status"] == "not_applicable"  # below the threshold
    case = await run(w["buyer"], case, "1.3.1.c")
    sourcing = step(case, "1.3.1.a")["l5"][0]["result"]
    assert [c["vendor_id"] for c in sourcing["candidates"]] == ["LabChem Supply Co"]
    assert [e["vendor_id"] for e in sourcing["excluded"]] == []  # Kestrel isn't for paste

    r = await act(
        w["buyer"],
        case,
        "complete_step",
        step="1.3.2",
        results={
            "1.3.2.a": {"reviewed": True},
            "1.3.2.b": {"vendor_id": "Kestrel Analytical", "terms": "net 30"},
        },
    )
    assert r.status_code == 409 and "On hold" in r.json()["detail"]["message"]
    case = await ok(
        w["buyer"],
        case,
        "complete_step",
        step="1.3.2",
        results={
            "1.3.2.a": {"reviewed": True},
            "1.3.2.b": {"vendor_id": "LabChem Supply Co", "terms": "net 30"},
        },
    )
    case = await run(w["buyer"], case, "1.6.1")
    assert step(case, "1.6.2")["status"] == "not_applicable"  # below the PO approval limit
    assert case["status"] == "approved"  # released: every checkpoint passed
    assert case["approvals"][0]["capacity"] == "released"

    case = await run(w["buyer"], case, "1.6.1.c")
    assert step(case, "1.6.1.c")["status"] == "failed"  # posted; the email waits to be sent
    po = erp.inserted[-1]
    assert (po["supplier"], po["items"][0]["rate"], po["items"][0]["project"]) == (
        "LabChem Supply Co",
        "38",
        GRANT,
    )
    assert erp.submitted == [("Purchase Order", po["name"])]
    assert await send_drafts(w["buyer"], case, "purchase_order") == 1
    case = await run(w["buyer"], case, "1.6.1.c")
    assert "acknowledgement" in step(case, "1.6.1.c")["l5"][0]["note"]
    case = await ok(w["buyer"], case, "log_acknowledgement", how="reply", note="Confirmed by email")
    assert case["approvals"][0]["valid"] is True  # an execution detail: approval still holds
    case = await run(w["buyer"], case, "1.6.1.c")
    assert step(case, "1.6.1.c")["status"] == "done"
    assert case["status"] == "approved"
    assert any("verified" in b for b in case["completion_blockers"])

    # A fresh snapshot holds the submitted PO: the posting is verified, the case completes
    fresh = await take_snapshot(
        w,
        db,
        purchase_orders=[
            *ap_payload()["purchase_orders"],
            {
                "id": po["name"],
                "vendor_id": "LabChem Supply Co",
                "date": TODAY.isoformat(),
                "status": "To Receive and Bill",
                "doc_status": "Submitted",
                "total": "1520",
                "lines": [
                    {
                        "id": "n1",
                        "item_code": "LC-PASTE",
                        "qty": "40",
                        "rate": "38",
                        "amount": "1520",
                        "cost_centre_id": CC,
                    }
                ],
            },
        ],
    )
    # The buyer isn't an opener of requests, but verifies the PO: they see the fresh snapshot
    assert (await w["buyer"].get("/api/v1/finance/sources", params={"workflow": PRQ})).json() == []
    listed = (await w["buyer"].get(f"/api/v1/finance/cases/{case['id']}/sources")).json()
    assert fresh["id"] in [s["id"] for s in listed]
    task = case["posting_tasks"][0]
    r = await w["buyer"].post(
        f"/api/v1/finance/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": fresh["id"]},
    )
    assert r.status_code == 200, r.text
    case = await ok(w["buyer"], case, "complete")
    assert case["status"] == "completed"
    tiles = (await w["buyer"].get("/api/v1/finance/dashboard")).json()["workflows"]
    cycle = next(m for t in tiles if t["key"] == PRQ for m in t["measures"] if m["id"] == "AP1.M1")
    assert cycle["value"] is not None


async def test_the_request_agents_say_what_they_need(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await opened(w["req"], snap)
    case = await ok(
        w["req"],
        case,
        "complete_step",
        step="1.1.1",
        results=need([("LC-PASTE", "10")], grant_id=OLD_GRANT),
    )
    case = await run(w["req"], case, "1.1.2")
    case = await run(w["req"], case, "1.2.1")
    grant = step(case, "1.2.1")["l5"][1]["result"]
    assert grant["allowed"] is False
    assert any("ended on 2026-06-30" in p for p in grant["problems"])
    assert any("isn't allowed on this grant" in p for p in grant["problems"])


@pytest.mark.requirement("AP1.P1")
async def test_a_request_without_budget_codes_is_flagged(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db, purchase_orders=[])  # no history to suggest one
    case = await opened(w["req"], snap)
    case = await ok(
        w["req"],
        case,
        "complete_step",
        step="1.1.1",
        results=need([("LC-PASTE", "10")], cost_centre_id=None, lab_id=None),
    )
    # The agent doesn't run: the case says what to fill in, and where
    needs = step(case, "1.1.2")["needs"]
    assert needs["fix_step"] == "1.1.1" and "a cost centre, a lab" in needs["message"]
    r = await act(w["req"], case, "run_agent_step", step="1.1.2")
    assert r.status_code == 409 and "Fix it in step 1.1.1" in r.json()["detail"]["message"]
    fresh = (await w["req"].get(f"/api/v1/finance/cases/{case['id']}")).json()
    assert step(fresh, "1.1.2")["status"] == "pending"
    queue = (await w["req"].get("/api/v1/finance/dashboard")).json()["my_queue"]
    assert [(q["step_key"], q["step_title"][:30]) for q in queue] == [
        ("1.1.1", "Fix before the agent runs: cho")
    ]
    # Sent back, the form starts from what was filled in; fixed, the agent runs
    case = await ok(w["req"], case, "redo_step", step="1.1.1", reason="add the coding")
    previous = step(case, "1.1.1")["l5"][0]["previous"]
    assert previous["lines"][0]["item_code"] == "LC-PASTE" and previous["cost_centre_id"] is None
    case = await ok(w["req"], case, "complete_step", step="1.1.1",
                    results=need([("LC-PASTE", "10")]))  # fmt: skip
    case = await run(w["req"], case, "1.1.2")
    assert step(case, "1.1.2")["status"] == "done" and step(case, "1.1.2")["needs"] is None


@pytest.mark.requirement("AP1.P2")
async def test_an_urgent_buy_is_never_hidden(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await opened(w["req"], snap)
    case = await ok(
        w["req"],
        case,
        "complete_step",
        step="1.1.1",
        results=need([("LC-PASTE", "10")], needed_by=(TODAY - timedelta(days=3)).isoformat()),
    )
    case = await run(w["req"], case, "1.1.2")
    assert step(case, "1.1.2")["l5"][2]["result"]["urgent"] is True
    tasks = [t for t in case["review_tasks"] if t["subject"] == "Urgent buy"]
    assert len(tasks) == 1 and tasks[0]["blocking"] is True


async def test_a_query_sends_the_request_back_and_counts_as_rework(
    world: World, db: AsyncSession
) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await to_budget_owner(w, snap, [("LC-PASTE", "10")])
    case = await ok(
        w["bo"],
        case,
        "complete_step",
        step="1.2.2",
        results={
            "1.2.2.a": {"reviewed": True},
            "1.2.2.b": {"decision": "query", "comment": "Which project?"},
        },
    )
    assert step(case, "1.1.1")["status"] == "pending"
    tile = (await w["req"].get("/api/v1/finance/dashboard")).json()["workflows"]
    rework = next(m for t in tile if t["key"] == PRQ for m in t["measures"] if m["id"] == "AP1.M2")
    assert rework["value"] == "100.0"

    other = await to_budget_owner(w, snap, [("LC-PASTE", "10")])
    other = await ok(
        w["bo"],
        other,
        "complete_step",
        step="1.2.2",
        results={
            "1.2.2.a": {"reviewed": True},
            "1.2.2.b": {"decision": "reject", "comment": "Not this year"},
        },
    )
    assert other["status"] == "cancelled"


@pytest.mark.requirement("AP1.R1")
async def test_quotes_are_required_above_the_threshold(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await opened(w["req"], snap, selection={"erp_request_id": "MAT-MR-1"})
    results = need([("LE-UVVIS", "1")], grant_id=GRANT)
    case = await ok(w["req"], case, "complete_step", step="1.1.1", results=results)
    case = await run(w["req"], case, "1.1.2")
    case = await run(w["req"], case, "1.2.1")
    assert step(case, "1.2.1")["l5"][2]["result"]["quotes_required"] is True
    assert step(case, "1.2.1")["l5"][0]["result"]["within_budget"] is False
    approve = {"1.2.2.a": {"reviewed": True}, "1.2.2.b": {"decision": "approve"}}
    r = await act(w["bo"], case, "complete_step", step="1.2.2", results=approve)
    assert r.status_code == 409 and "say why" in r.json()["detail"]["message"]
    assert "flagged this request" in r.json()["detail"]["message"]
    approve["1.2.2.b"]["comment"] = "Board approved the instrument from reserves"
    case = await ok(w["bo"], case, "complete_step", step="1.2.2", results=approve)
    case = await run(w["buyer"], case, "1.3.1.a")
    case = await run(w["buyer"], case, "1.3.1.b")
    assert step(case, "1.3.1.b")["status"] == "failed"  # drafted, not sent yet
    assert await send_drafts(w["buyer"], case, "rfq") == 2  # GemTech and Spectra (emails)
    case = await run(w["buyer"], case, "1.3.1.b")
    case = await run(w["buyer"], case, "1.3.1.c")
    assert "2 of 3 quotes" in step(case, "1.3.1.c")["l5"][0]["note"]  # the ERP's two

    upload = await w["buyer"].post(
        f"/api/v1/finance/cases/{case['id']}/artifacts",
        files={"file": ("quote.txt", b"Precision Optics quote Q-77: 49,500", "text/plain")},
        data={"kind": "quote"},
    )
    assert upload.status_code == 201, upload.text
    case = await ok(
        w["buyer"],
        case,
        "record_quote",
        vendor_id="GemTech Instruments",
        vendor_name="Precision Optics Inc",
        reference="Q-77",
        total="49500",
        lead_time_days=30,
        document_id=upload.json()["id"],
        rates={"LE-UVVIS": "49500"},
    )
    case = await run(w["buyer"], case, "1.3.1.c")
    comparison = step(case, "1.3.1.c")["l5"][0]["result"]
    assert [q["reference"] for q in comparison["quotes"]] == ["SQ-2", "SQ-1", "Q-77"]
    assert (comparison["cheapest"], comparison["fastest"]) == ("SQ-2", "Q-77")
    r = await act(
        w["buyer"],
        case,
        "complete_step",
        step="1.3.2",
        results={
            "1.3.2.a": {"reviewed": True},
            "1.3.2.b": {
                "vendor_id": "GemTech Instruments",
                "quote_reference": "SQ-1",
                "terms": "net 30",
            },
        },
    )
    assert r.status_code == 409 and "cheapest" in r.json()["detail"]["message"]


async def test_an_ended_grant_cant_be_approved(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await to_budget_owner(w, snap, [("LC-PASTE", "10")], grant_id=OLD_GRANT)
    assert step(case, "1.2.1")["l5"][1]["result"]["allowed"] is False
    r = await act(
        w["bo"],
        case,
        "complete_step",
        step="1.2.2",
        results={"1.2.2.a": {"reviewed": True}, "1.2.2.b": {"decision": "approve"}},
    )
    assert r.status_code == 409 and "grant can't take this charge" in r.json()["detail"]["message"]


@pytest.mark.requirement("AP1.G1")
async def test_no_po_goes_out_before_the_request_is_approved(
    world: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await to_budget_owner(w, snap, [("LC-PASTE", "10")])
    r = await act(w["buyer"], case, "run_agent_step", step="1.6.1.c")
    assert r.status_code == 409
    assert "released" in r.json()["detail"]["message"]
    assert erp.inserted == []
    assert any("not done yet" in b for b in case["blockers"])


@pytest.mark.requirement("AP1.R4")
async def test_a_new_vendor_is_onboarded_before_its_po(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await to_budget_owner(w, snap, [("LC-PASTE", "10")])
    case = await ok(
        w["bo"],
        case,
        "complete_step",
        step="1.2.2",
        results={"1.2.2.a": {"reviewed": True}, "1.2.2.b": {"decision": "approve"}},
    )
    case = await run(w["buyer"], case, "1.3.1.a")
    case = await run(w["buyer"], case, "1.3.1.c")
    case = await ok(
        w["buyer"],
        case,
        "complete_step",
        step="1.3.2",
        results={
            "1.3.2.a": {"reviewed": True},
            "1.3.2.b": {
                "new_vendor_name": "Nova Gem Tools",
                "new_vendor_email": "ap@novagem.example.com",
                "terms": "net 30",
            },
        },
    )
    onboarding = next(
        c for c in (await w["buyer"].get("/api/v1/finance/cases")).json() if c["workflow"] == VND
    )
    assert onboarding["title"] == "Onboard Nova Gem Tools"
    case = await run(w["buyer"], case, "1.6.1")
    assert step(case, "1.6.1")["status"] == "failed"
    assert onboarding["reference"] in step(case, "1.6.1")["l5"][0]["note"]
    assert any("AP1.R4" in b for b in case["blockers"])


# --- vendor onboarding -----------------------------------------------------------------------


async def _onboarding(w: World, db: AsyncSession) -> tuple[dict[str, Any], str]:
    snap = await take_snapshot(w, db)
    case = await opened(
        w["analyst"],
        snap,
        VND,
        {"vendor_name": "Nova Gem Tools", "contact_email": "ap@novagem.example.com"},
    )
    case = await run(w["analyst"], case, "1.5.1.a")
    assert step(case, "1.5.1.a")["status"] == "failed"  # drafted; a person sends it
    invite = next(m for m in case["messages"] if m["purpose"] == "vendor_invite")
    assert invite["audience"] == "invite" and invite["to_email"] == "ap@novagem.example.com"
    assert await send_drafts(w["analyst"], case, "vendor_invite") == 1
    case = await run(w["analyst"], case, "1.5.1.a")
    assert step(case, "1.5.1.a")["status"] == "done"
    body = await db.scalar(select(PodMessage.body).where(PodMessage.purpose == "vendor_invite"))
    token = body.split("/vendor/")[1].split()[0]
    return case, token


async def _portal_upload(client: AsyncClient, token: str, kind: str, name: str, text: str) -> Any:
    return await client.post(
        f"/api/v1/vendor-portal/{token}/documents",
        files={"file": (name, text.encode(), "text/plain")},
        data={"kind": kind},
    )


@pytest.mark.requirement("AP1.R3", "AP1.G2", "AP1.P3")
async def test_a_vendor_is_onboarded_through_the_portal_by_two_people(
    world: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = world
    case, token = await _onboarding(w, db)
    view = (await client.get(f"/api/v1/vendor-portal/{token}")).json()
    assert view["vendor_name"] == "Nova Gem Tools" and view["uploaded"] == []

    # AP1.G2 / P3: a bank letter a person uploads (e.g. from an email) doesn't count
    staff = await w["analyst"].post(
        f"/api/v1/finance/cases/{case['id']}/artifacts",
        files={"file": ("letter.txt", BANK_LETTER.encode(), "text/plain")},
        data={"kind": "bank_letter"},
    )
    assert staff.status_code == 201
    case = await run(w["analyst"], case, "1.5.1.b")
    assert "Waiting for the vendor to upload" in step(case, "1.5.1.b")["l5"][0]["note"]

    assert (await _portal_upload(client, token, "tax_form", "w9.txt", W9)).status_code == 201
    letter = await _portal_upload(client, token, "bank_letter", "bank.txt", BANK_LETTER + " ")
    assert letter.status_code == 201
    case = await run(w["analyst"], case, "1.5.1.b")
    read = step(case, "1.5.1.b")["l5"][0]["result"]
    assert (
        read["tax"]["tax_id_masked"] == "******4567"
        and read["bank"]["account_masked"] == "********6789"
    )
    assert "000123456789" not in str(case)  # the full number never leaves the case

    case = await run(w["analyst"], case, "1.5.1.c")
    assert "sanctions list isn't loaded" in step(case, "1.5.1.c")["l5"][0]["note"]
    await sanctions.load(db, SDN_CSV.encode(), "test")
    await db.commit()
    case = await run(w["analyst"], case, "1.5.1.c")
    assert step(case, "1.5.1.c")["status"] == "done"
    assert step(case, "1.5.1.c")["l5"][0]["result"]["hits"] == []

    call = {
        "phone_number": "+1 555 0100",
        "number_source": "public directory",
        "spoke_with": "Dana Ortiz",
        "called_at": utcnow().isoformat(),
        "confirmed": True,
    }
    r = await act(
        w["analyst"],
        case,
        "complete_step",
        step="1.5.2.a",
        results={"1.5.2.a": {**call, "account_last4": "1111"}},
    )
    assert r.status_code == 409 and "don't match" in r.json()["detail"]["message"]
    case = await ok(
        w["analyst"],
        case,
        "complete_step",
        step="1.5.2.a",
        results={"1.5.2.a": {**call, "account_last4": "6789"}},
    )

    case = await ok(
        w["approver"],
        case,
        "complete_step",
        step="1.5.2.b",
        results={"1.5.2.b": {"approved": True}},
    )
    assert case["status"] == "approved"
    supplier = erp.inserted[-1]
    assert (supplier["supplier_name"], supplier["tax_id"], supplier["email_id"]) == (
        "Nova Gem Tools",
        "84-1234567",
        "ap@novagem.example.com",
    )
    assert case["posting_tasks"][0]["status"] == "recorded_unverified"
    assert (await client.get(f"/api/v1/vendor-portal/{token}")).status_code == 404  # closed

    # AP1.G2: a reply carrying bank details raises a blocking review task
    reply = PodMessage(
        case_id=case["id"],
        direction=Direction.INBOUND,
        purpose="vendor_invite",
        status=MessageStatus.RECEIVED,
        to_email="ap@novagem.example.com",
        subject="Our new bank",
        body="Please use IBAN GB29NWBK60161331926819",
    )
    vnd = await db.get(PodCase, case["id"])
    assert vnd is not None
    await vnd_service.read_reply(db, vnd, reply, None)  # type: ignore[arg-type]
    await db.commit()
    subjects = list(
        await db.scalars(select(PodReviewTask.subject).where(PodReviewTask.case_id == vnd.id))
    )
    assert "Bank details by email" in subjects


@pytest.mark.requirement("AP1.R3")
async def test_the_second_approver_must_be_another_person(
    world: World, db: AsyncSession, person: PersonFn, client: AsyncClient
) -> None:
    w = world
    _, both = await person("both@example.com", Cap.AP_ANALYST, Cap.VENDOR_APPROVER)
    case, token = await _onboarding(w, db)
    await _portal_upload(client, token, "tax_form", "w9.txt", W9)
    await _portal_upload(client, token, "bank_letter", "bank.txt", BANK_LETTER)
    await sanctions.load(db, SDN_CSV.encode(), "test")
    await db.commit()
    case = await run(w["analyst"], case, "1.5.1.b")
    case = await run(w["analyst"], case, "1.5.1.c")
    case = await ok(
        both,
        case,
        "complete_step",
        step="1.5.2.a",
        results={
            "1.5.2.a": {
                "phone_number": "+1 555 0100",
                "number_source": "public directory",
                "spoke_with": "Dana",
                "called_at": utcnow().isoformat(),
                "account_last4": "6789",
                "confirmed": True,
            }
        },
    )
    r = await act(
        both, case, "complete_step", step="1.5.2.b", results={"1.5.2.b": {"approved": True}}
    )
    assert r.status_code == 409
    assert "whoever did 1.5.2.a" in r.json()["detail"]["message"]


async def test_a_sanctions_match_blocks_until_cleared(
    world: World, db: AsyncSession, client: AsyncClient
) -> None:
    w = world
    snap = await take_snapshot(w, db)
    case = await opened(
        w["analyst"],
        snap,
        VND,
        {"vendor_name": "Aerocaribbean Airlines", "contact_email": "a@x.example.com"},
    )
    await run(w["analyst"], case, "1.5.1.a")
    await send_drafts(w["analyst"], case, "vendor_invite")
    case = await run(w["analyst"], case, "1.5.1.a")
    body = await db.scalar(select(PodMessage.body).where(PodMessage.case_id == case["id"]))
    token = body.split("/vendor/")[1].split()[0]
    w9 = W9.replace("Nova Gem Tools LLC", "Aerocaribbean Airlines")
    await _portal_upload(client, token, "tax_form", "w9.txt", w9)
    await _portal_upload(client, token, "bank_letter", "bank.txt", BANK_LETTER)
    await sanctions.load(db, SDN_CSV.encode(), "test")
    await db.commit()
    case = await run(w["analyst"], case, "1.5.1.b")
    case = await run(w["analyst"], case, "1.5.1.c")
    hits = step(case, "1.5.1.c")["l5"][0]["result"]["hits"]
    assert hits and hits[0]["entry_id"] == "36"
    assert any(
        t["subject"] == "Sanctions screening" and t["blocking"] for t in case["review_tasks"]
    )
    assert any("review task" in b for b in case["blockers"])


async def test_mail_is_sent_only_by_the_purposes_capacity(world: World, db: AsyncSession) -> None:
    w = world
    await _onboarding(w, db)
    snap = await take_snapshot(w, db)
    prq = await opened(w["req"], snap, selection={"erp_request_id": "MAT-MR-1"})
    prq = await ok(
        w["req"],
        prq,
        "complete_step",
        step="1.1.1",
        results=need([("LE-UVVIS", "1")], grant_id=GRANT),
    )
    for key in ("1.1.2", "1.2.1"):
        prq = await run(w["req"], prq, key)
    prq = await ok(
        w["bo"],
        prq,
        "complete_step",
        step="1.2.2",
        results={
            "1.2.2.a": {"reviewed": True},
            "1.2.2.b": {"decision": "approve", "comment": "From reserves"},
        },
    )
    prq = await run(w["buyer"], prq, "1.3.1.a")
    prq = await run(w["buyer"], prq, "1.3.1.b")
    rfq = next(m for m in prq["messages"] if m["purpose"] == "rfq")
    r = await w["bo"].post(
        f"/api/v1/finance/messages/{rfq['id']}/send",
        json={"expected_version": rfq["version"], "checks": CHECKS},
    )
    assert r.status_code in (403, 404)


async def test_the_requirement_is_covered() -> None:
    from pathlib import Path

    from src.app.finance_pod.requirements.ap import AP1
    from src.app.finance_pod.requirements.coverage import problems
    from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey

    sources = "\n".join(p.read_text() for p in Path(__file__).parent.rglob("test_*.py"))
    specs = [WORKFLOWS[WorkflowKey(k)] for k in AP1.workflows]
    assert problems(AP1, specs, sources) == []


async def test_people_pick_from_the_case_catalogue(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take_snapshot(w, db)
    sources = (await w["req"].get(f"/api/v1/finance/sources?workflow={PRQ}")).json()
    assert sources[0]["id"] == snap["id"]
    assert (
        await w["bo"].get(f"/api/v1/finance/sources?workflow={PRQ}")
    ).json() == []  # not an opener
    cat = (
        await w["req"].get(f"/api/v1/finance/sources/{snap['id']}/catalogue?workflow={PRQ}")
    ).json()
    paste = next(i for i in cat["items"] if i["code"] == "LC-PASTE")
    assert (paste["catalogue_rate"], paste["contract_rates"]) == ("42", {"LabChem Supply Co": "38"})
    assert [r["id"] for r in cat["purchase_requests"]] == ["MAT-MR-1"]
    case = await opened(w["req"], snap)
    cat = (await w["bo"].get(f"/api/v1/finance/cases/{case['id']}/catalogue")).json()
    assert {v["id"]: v["detail"] for v in cat["vendors"]}["Kestrel Analytical"] == "On hold"


async def test_admins_load_the_sanctions_list(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    assert (await w["analyst"].get("/api/v1/finance/sanctions")).json()["loaded"] is False
    monkeypatch.setattr(
        sanctions, "transport", httpx.MockTransport(lambda r: httpx.Response(200, text=SDN_CSV))
    )
    assert (await w["analyst"].post("/api/v1/finance/sanctions/refresh")).status_code == 403
    assert w.admin is not None
    r = await w.admin.post("/api/v1/finance/sanctions/refresh")
    assert r.status_code == 200, r.text
    assert (r.json()["loaded"], r.json()["entries"]) == (True, 2)
