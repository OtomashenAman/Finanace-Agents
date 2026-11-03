"""AR-1 Client Account & Credit Set-Up: a client applies through the portal, the agents read,
screen and score, the credit controller decides, the client goes to a stand-in ERPNext and
its limit is reviewed. Each rule, guardrail and pain point is proved by a marked test."""

import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.finance_pod import sanctions
from src.app.finance_pod.flows.ar_client_account import service as arc
from src.app.service_pod.core.cases.models import PodCase, PodReviewTask
from src.app.service_pod.core.messaging.models import ArtifactChannel, PodArtifact, PodMessage
from src.app.service_pod.core.snapshots.models import PodSnapshotSource
from tests.finance_pod.ap_data import SDN_CSV, ap_payload
from tests.finance_pod.conftest import Cap, PersonFn, World, step
from tests.finance_pod.fake_erpnext import FakeErpNext
from tests.finance_pod.test_ap1 import act, ok, run
from tests.service_pod.conftest import import_snapshot

CLT = "ar_client_account"
CHECKS = {"recipient": True, "mapping": True, "tone": True}
EXISTING = {"id": "Brilliant Gems", "name": "Brilliant Gems LLC", "status": "Active",
            "credit_limit": "50000", "terms_days": 30}  # fmt: skip
W9 = (
    "Form W-9 Request for Taxpayer Identification Number and Certification\n"
    "Name (as shown on your income tax return): Lumen Gem Traders LLC\n"
    "Employer identification number: 84-7654321\n"
)
REGISTRATION = "State of New York certificate of incorporation: Lumen Gem Traders LLC, 2015"


def application(**changes: Any) -> dict[str, Any]:
    return {
        "legal_name": "Lumen Gem Traders LLC",
        "tax_id": "84-7654321",
        "country": "United States",
        "address": "580 Fifth Avenue, New York, NY 10036",
        "billing_email": "ap@lumengem.example.com",
        "established_year": 2015,
        "requested_limit": "20000",
        "requested_terms_days": 30,
        "trade_references": [
            {"company": "Brilliant Gems LLC", "contact_email": "ap@brilliantgems.example.com"},
            {"company": "Rivera Fine Jewelry", "contact_email": "accounts@riverafj.example.com"},
        ],
        **changes,
    }


async def take(w: World, db: AsyncSession, **changes: Any) -> dict[str, Any]:
    assert w.admin and w.entity and w.source
    payload = ap_payload(
        source_reference=f"read {uuid.uuid4()}", **{"clients": [EXISTING], **changes}
    )
    r = await import_snapshot(w.admin, w.entity, payload)
    assert r.status_code in (200, 201), r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    db.add(PodSnapshotSource(snapshot_id=uuid.UUID(snap["id"]), data_source_id=w.source.id))
    await db.commit()
    return snap


@pytest.fixture
async def desk(world: World, person: PersonFn, db: AsyncSession) -> World:
    """The world plus a credit controller and a billing analyst, and the sanctions list."""
    world.users["credit"], world.clients["credit"] = await person(
        "credit@example.com", Cap.CREDIT_CONTROLLER
    )
    world.users["billing"], world.clients["billing"] = await person(
        "billing@example.com", Cap.BILLING_ANALYST
    )
    await sanctions.load(db, SDN_CSV.encode(), "test")
    await db.commit()
    return world


async def opened(w: World, snap: dict[str, Any], name: str = "Lumen Gem Traders LLC") -> Any:
    r = await w["billing"].post(
        "/api/v1/finance/cases",
        json={"workflow": CLT, "snapshot_id": snap["id"], "title": f"Open {name}",
              "selection": {"client_name": name, "contact_email": "ap@lumengem.example.com"}},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    case = r.json()
    case = await ok(w["billing"], case, "invite_client")
    invite = next(m for m in case["messages"] if m["purpose"] == "client_invite")
    sent = await w["billing"].post(
        f"/api/v1/finance/messages/{invite['id']}/send",
        json={"expected_version": invite["version"], "checks": CHECKS},
    )
    assert sent.status_code == 200, sent.text
    return case


async def token_of(db: AsyncSession, case: dict[str, Any], purpose: str) -> str:
    body = await db.scalar(
        select(PodMessage.body)
        .where(PodMessage.case_id == uuid.UUID(case["id"]), PodMessage.purpose == purpose)
        .order_by(PodMessage.created_at.desc())
    )
    assert body is not None
    return str(body.split("/client/")[1].split()[0])


async def upload(client: AsyncClient, token: str, kind: str, name: str, text: str) -> Any:
    return await client.post(
        f"/api/v1/client-portal/{token}/documents",
        files={"file": (name, text.encode(), "text/plain")},
        data={"kind": kind},
    )


async def apply(client: AsyncClient, token: str, **changes: Any) -> Any:
    return await client.post(
        f"/api/v1/client-portal/{token}/application", json=application(**changes)
    )


async def to_decision(w: World, db: AsyncSession, client: AsyncClient) -> dict[str, Any]:
    snap = await take(w, db)
    case = await opened(w, snap)
    token = await token_of(db, case, "client_invite")
    assert (await upload(client, token, "tax_form", "w9.txt", W9)).status_code == 201
    assert (await upload(client, token, "registration", "reg.txt", REGISTRATION)).status_code == 201
    r = await apply(client, token)
    assert r.status_code == 200, r.text
    assert {d["kind"] for d in r.json()["uploaded"]} == {"tax_form", "registration"}
    case = await run(w["credit"], case, "1.1.2")
    assert step(case, "1.1.2")["status"] == "done", step(case, "1.1.2")
    return await run(w["credit"], case, "1.2.1")


async def fresh_with(w: World, db: AsyncSession, customer: dict[str, Any], **changes: Any) -> Any:
    client = {
        "id": customer["name"], "name": customer["customer_name"], "status": "Active",
        "email": customer["email_id"], "terms_days": 30,
        "credit_limit": customer["credit_limits"][0]["credit_limit"]
        if customer["credit_limits"] else None,
        **changes,
    }  # fmt: skip
    return await take(w, db, clients=[EXISTING, client])


# --- the whole application ---------------------------------------------------------------


@pytest.mark.requirement("AR1.R1", "AR1.G1", "AR1.P1", "AR1.P3")
async def test_a_client_applies_through_the_portal_and_gets_credit(
    desk: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = desk
    case = await to_decision(w, db, client)
    assert step(case, "1.1.1")["l5"][0]["done_by"] == "Through the portal"
    risk = step(case, "1.2.1")["l5"][0]["result"]
    proposal = step(case, "1.2.1")["l5"][1]["result"]
    assert risk["band"] == "low" and risk["history"].startswith("new to the books")
    assert (proposal["deposit_only"], proposal["credit_limit"], proposal["terms_days"]) == (
        False, "20000.00", 30,
    )  # fmt: skip
    # AR1.P3: the documents came through the portal into the case
    docs = list(await db.scalars(select(PodArtifact).where(PodArtifact.case_id == case["id"])))
    assert {d.channel for d in docs} == {ArtifactChannel.CLIENT_PORTAL}

    # AR1.G1: the agent's proposal alone creates nothing; a billing analyst can't decide
    assert case["status"] == "draft" and erp.inserted == []
    decision = {"1.2.2.a": {"decision": "approve_credit", "credit_limit": "15000",
                            "terms_days": 30}}  # fmt: skip
    r = await act(w["billing"], case, "complete_step", step="1.2.2", results=decision)
    assert r.status_code == 409 and "credit controller" in r.json()["detail"]["message"]
    case = await ok(w["credit"], case, "complete_step", step="1.2.2", results=decision)
    assert case["status"] == "approved"  # released: the controller's decision

    # AR1.R1: the customer carries exactly the approved terms, once
    customer = erp.inserted[-1]
    assert (customer["customer_name"], customer["payment_terms"], customer["tax_category"]) == (
        "Lumen Gem Traders LLC", "Net 30", "Domestic",
    )  # fmt: skip
    assert customer["credit_limits"][0]["credit_limit"] == "15000.00"
    task = case["posting_tasks"][0]
    assert (task["kind"], task["status"]) == ("create_customer", "recorded_unverified")
    portal = await client.get(f"/api/v1/client-portal/{await token_of(db, case, 'client_invite')}")
    assert portal.status_code == 404  # decided: the application is closed

    # AR1.P1: set up once, in the ERP; verified by a fresh snapshot
    case = await run(w["credit"], case, "1.3.1")
    assert "verify it with a fresh snapshot" in step(case, "1.3.1")["l5"][0]["note"]
    fresh = await fresh_with(w, db, customer)
    r = await w["credit"].post(
        f"/api/v1/finance/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": fresh["id"]},
    )
    assert r.status_code == 200, r.text
    case = await run(w["credit"], case, "1.3.1")
    created = step(case, "1.3.1")["l5"][0]["result"]
    assert created["erp_customer"] == "Lumen Gem Traders LLC"
    assert "not connected" in created["lab_system"]
    case = await run(w["credit"], case, "1.3.2")
    assert step(case, "1.3.2")["l5"][0]["result"]["suggestion"] == "keep"
    case = await ok(w["credit"], case, "complete")
    assert case["status"] == "completed"
    tiles = (await w["credit"].get("/api/v1/finance/dashboard")).json()["workflows"]
    measures = {m["id"]: m["value"] for t in tiles if t["key"] == CLT for m in t["measures"]}
    assert measures["AR1.M1"] is not None and measures["AR1.M2"] == "0.00"


@pytest.mark.requirement("AR1.R2")
async def test_gaps_go_back_to_the_client_who_then_starts_on_deposit(
    desk: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = desk
    snap = await take(w, db)
    case = await opened(w, snap)
    token = await token_of(db, case, "client_invite")
    r = await apply(client, token)
    assert r.status_code == 409 and "tax form first" in r.json()["detail"]["message"]
    await upload(client, token, "tax_form", "w9.txt", W9)
    assert (await apply(client, token, trade_references=[])).status_code == 200

    case = await run(w["credit"], case, "1.1.2")
    note = step(case, "1.1.2")["l5"][0]["note"]
    assert step(case, "1.1.2")["status"] == "failed"
    assert "registration" in note and "trade reference" in note and "drafted" in note
    gaps = next(m for m in case["messages"] if m["purpose"] == "client_gaps")
    assert gaps["to_email"] == "ap@lumengem.example.com" and "registration" in gaps["body"]

    # The client fixes it on the new link: a registration, and no credit after all
    token = await token_of(db, case, "client_gaps")
    await upload(client, token, "registration", "reg.txt", REGISTRATION)
    assert (await apply(client, token, trade_references=[], requested_limit="0")).status_code == 200
    case = await run(w["credit"], case, "1.1.2")
    case = await run(w["credit"], case, "1.2.1")
    proposal = step(case, "1.2.1")["l5"][1]["result"]
    assert proposal["deposit_only"] is True and "AR1.R2" in proposal["reason"]
    case = await ok(w["credit"], case, "complete_step", step="1.2.2",
                    results={"1.2.2.a": {"decision": "deposit_only"}})  # fmt: skip
    customer = erp.inserted[-1]
    assert (customer["deposit_only"], customer["credit_limits"], customer["payment_terms"]) == (
        1, [], "Due on receipt",
    )  # fmt: skip
    tiles = (await w["credit"].get("/api/v1/finance/dashboard")).json()["workflows"]
    errors = next(m for t in tiles if t["key"] == CLT for m in t["measures"] if m["id"] == "AR1.M2")
    assert errors["value"] == "100.00"


async def test_a_limit_above_the_proposal_needs_a_reason(
    desk: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = desk
    case = await to_decision(w, db, client)
    more = {"decision": "approve_credit", "credit_limit": "30000", "terms_days": 30}
    r = await act(w["credit"], case, "complete_step", step="1.2.2", results={"1.2.2.a": more})
    assert r.status_code == 409 and "say why" in r.json()["detail"]["message"]
    odd = {"decision": "approve_credit", "credit_limit": "5000", "terms_days": 20}
    r = await act(w["credit"], case, "complete_step", step="1.2.2", results={"1.2.2.a": odd})
    assert r.status_code == 409 and "0, 30, 45" in r.json()["detail"]["message"]
    reasoned = {"1.2.2.a": {**more, "reason": "Parent company guarantee"}}
    case = await ok(w["credit"], case, "complete_step", step="1.2.2", results=reasoned)
    assert erp.inserted[-1]["credit_limits"][0]["credit_limit"] == "30000.00"


async def test_a_declined_application_creates_nothing(
    desk: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = desk
    case = await to_decision(w, db, client)
    case = await ok(
        w["credit"],
        case,
        "complete_step",
        step="1.2.2",
        results={"1.2.2.a": {"decision": "decline", "reason": "Not a trade client"}},
    )
    assert case["status"] == "cancelled" and erp.inserted == []


async def test_a_sanctions_match_blocks_the_account(
    desk: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = desk
    snap = await take(w, db)
    case = await opened(w, snap, name="Nova Gem Trading")
    token = await token_of(db, case, "client_invite")
    await upload(client, token, "tax_form", "w9.txt", W9)
    await upload(client, token, "registration", "reg.txt", REGISTRATION)
    await apply(client, token)
    case = await run(w["credit"], case, "1.1.2")
    review = next(t for t in case["review_tasks"] if t["subject"] == "Sanctions screening")
    assert review["blocking"] is True and "NOVA GEM TRADING" in review["detail"]
    queue = (await w["credit"].get("/api/v1/finance/dashboard")).json()["my_queue"]
    assert ("review", "Sanctions screening") in {(q["type"], q["step_title"]) for q in queue}
    case = await run(w["credit"], case, "1.2.1")
    factors = step(case, "1.2.1")["l5"][0]["result"]["factors"]
    assert any(f["points"] == -40 for f in factors)
    case = await ok(w["credit"], case, "complete_step", step="1.2.2",
                    results={"1.2.2.a": {"decision": "deposit_only"}})  # fmt: skip
    assert case["status"] == "draft" and erp.inserted == []  # the review task blocks it


async def test_an_existing_client_isnt_opened_again(desk: World, db: AsyncSession) -> None:
    w = desk
    snap = await take(w, db)
    first = await opened(w, snap)
    r = await w["credit"].post(
        "/api/v1/finance/cases",
        json={"workflow": CLT, "snapshot_id": snap["id"], "title": "Twice",
              "selection": {"client_name": "lumen gem traders llc",
                            "contact_email": "ap@lumengem.example.com"}},
    )  # fmt: skip
    assert r.status_code == 422 and first["reference"] in r.json()["detail"]["message"]
    r = await w["credit"].post(
        "/api/v1/finance/cases",
        json={"workflow": CLT, "snapshot_id": snap["id"], "title": "Again",
              "selection": {"client_name": "Brilliant Gems LLC",
                            "contact_email": "ap@brilliantgems.example.com"}},
    )  # fmt: skip
    assert r.status_code == 422 and "already a client" in r.json()["detail"]["message"]


@pytest.mark.requirement("AR1.R3", "AR1.P2")
async def test_the_daily_review_flags_a_limit_nearly_used(
    desk: World, db: AsyncSession, erp: FakeErpNext, client: AsyncClient
) -> None:
    w = desk
    case = await to_decision(w, db, client)
    case = await ok(w["credit"], case, "complete_step", step="1.2.2",
                    results={"1.2.2.a": {"decision": "approve_credit", "credit_limit": "15000",
                                         "terms_days": 30}})  # fmt: skip
    customer = erp.inserted[-1]
    task = case["posting_tasks"][0]
    fresh = await fresh_with(w, db, customer)
    await w["credit"].post(
        f"/api/v1/finance/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": fresh["id"]},
    )
    case = await run(w["credit"], case, "1.3.1")
    case = await run(w["credit"], case, "1.3.2")

    # Later the books show 14,400 of 15,000 used, one invoice 75 days overdue
    invoice = {
        "id": "SI-9", "client_id": "Lumen Gem Traders LLC", "posting_date": "2026-07-20",
        "due_date": "2026-08-19", "status": "Overdue", "doc_status": "Submitted",
        "currency": "USD", "net_total": "14400", "total": "14400", "outstanding": "14400",
        "lines": [],
    }  # fmt: skip
    later = await take(
        w, db,
        clients=[EXISTING, {"id": "Lumen Gem Traders LLC", "name": "Lumen Gem Traders LLC",
                            "status": "Active", "credit_limit": "15000", "terms_days": 30,
                            "email": "ap@lumengem.example.com"}],
        sales_invoices=[invoice],
    )  # fmt: skip
    assert later["id"]
    row = await db.get(PodCase, uuid.UUID(case["id"]))
    assert row is not None
    assert await arc.review_client(db, row) == "review"
    await db.commit()
    task_row = await db.scalar(
        select(PodReviewTask).where(
            PodReviewTask.case_id == row.id, PodReviewTask.subject == arc.REVIEW
        )
    )
    assert task_row is not None and "96.00% of the limit" in task_row.detail
    assert row.state["_review"]["outstanding"] == str(Decimal("14400.00"))


async def test_a_paper_application_is_completed_before_the_agent_reads_it(
    desk: World, db: AsyncSession, erp: FakeErpNext
) -> None:
    """Entered in the app (not the client's portal): what's missing is fixed in 1.1.1, the
    agent doesn't run and nothing is emailed."""
    w = desk
    snap = await take(w, db)
    r = await w["credit"].post(
        "/api/v1/finance/cases",
        json={"workflow": CLT, "snapshot_id": snap["id"], "title": "Paper",
              "selection": {"client_name": "Lumen Gem Traders LLC",
                            "contact_email": "ap@lumengem.example.com"}},
    )  # fmt: skip
    case = r.json()
    paper = {"1.1.1.a": {**application(), "trade_references": []}, "1.1.1.b": {}}
    case = await ok(w["credit"], case, "complete_step", step="1.1.1", results=paper)
    needs = step(case, "1.1.2")["needs"]
    assert needs["fix_step"] == "1.1.1" and "choose the tax form" in needs["message"]
    assert "trade references" in needs["message"]
    refused = await act(w["credit"], case, "run_agent_step", step="1.1.2")
    assert (
        refused.status_code == 409 and "Fix it in step 1.1.1" in refused.json()["detail"]["message"]
    )
    assert [m for m in case["messages"] if m["purpose"] == "client_gaps"] == []
