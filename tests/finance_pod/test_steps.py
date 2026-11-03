"""The step engine on a demo workflow: order, capacity, segregation of duties, agent runs and
failures, not-applicable steps, redo, rules, sign-offs and who sees which case."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.entities.models import LegalEntity
from tests.finance_pod.conftest import AGENT, Cap, PersonFn, act, open_demo, step


async def _open(client: AsyncClient, snapshot: dict[str, Any], **kw: Any) -> dict[str, Any]:
    r = await open_demo(client, snapshot, **kw)
    assert r.status_code == 201, r.text
    case: dict[str, Any] = r.json()
    return case


async def _ok(client: AsyncClient, case: dict[str, Any], action: str, **p: Any) -> dict[str, Any]:
    r = await act(client, case, action, **p)
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


async def test_a_case_opens_with_every_l5_pending(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    case = await _open(req, snapshot)
    assert [(s["key"], s["kind"], s["status"]) for s in case["steps"]] == [
        ("1.1", "person", "pending"),
        ("1.2", "agent", "pending"),
        ("1.3", "person", "pending"),
        ("1.4", "person", "pending"),
    ]
    assert case["stage"] == "1.1"
    assert step(case, "1.1")["blocked"] is None
    assert "waits on 1.1" in step(case, "1.2")["blocked"]
    assert step(case, "1.1")["l5"][0]["result_schema"]["required"] == ["item", "quantity"]
    assert any("not done yet" in b for b in case["blockers"])


async def test_steps_go_in_order_by_the_right_people(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER)
    case = await _open(req, snapshot)

    r = await act(req, case, "complete_step", step="1.3")
    assert r.status_code == 409
    assert "capacity" in r.json()["detail"]["message"]
    r = await act(req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x"}})
    assert r.status_code == 422
    assert r.json()["detail"]["message"] == "Quantity: field required"  # as the form names it

    case = await _ok(
        req,
        case,
        "complete_step",
        step="1.1",
        results={"1.1.a": {"item": "Pipettes", "quantity": 20}},
    )
    assert step(case, "1.1")["status"] == "done"
    assert step(case, "1.1")["l5"][0]["done_by"] == "Req"

    r = await act(owner, case, "complete_step", step="1.3")
    assert r.status_code == 409
    assert "waits on 1.2" in r.json()["detail"]["message"]

    case = await _ok(req, case, "run_agent_step", step="1.2")
    assert step(case, "1.2")["l5"][0]["result"] == {"note": "checked 50"}
    assert step(case, "1.2")["l5"][0]["done_by"] == "Agent"

    case = await _ok(owner, case, "complete_step", step="1.3")
    # Small request: the buyer's step doesn't apply, and says why
    assert step(case, "1.4")["status"] == "not_applicable"
    assert step(case, "1.4")["l5"][0]["note"] == "Below the quote threshold (100)"
    assert step(case, "1.4")["l5"][0]["done_by"] == "System"
    assert case["blockers"] == []
    assert case["stage"] is None

    r = await act(req, case, "approve")
    assert r.status_code == 409  # neither the capacity nor allowed: they opened it
    case = await _ok(owner, case, "approve")
    assert case["status"] == "approved"
    assert case["approvals"][0]["capacity"] == "budget_owner"


async def test_segregation_of_duties_binds_admins_too(
    admin: AsyncClient, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    case = await _open(admin, snapshot)
    case = await _ok(
        admin, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    case = await _ok(admin, case, "run_agent_step", step="1.2")
    r = await act(admin, case, "complete_step", step="1.3")
    assert r.status_code == 409
    assert "someone other than who opened the case" in r.json()["detail"]["message"]


async def test_a_step_done_by_one_person_blocks_them_on_a_distinct_step(
    person: PersonFn, admin: AsyncClient, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, both = await person("both@example.com", Cap.REQUESTER, Cap.BUDGET_OWNER)
    case = await _open(admin, snapshot)  # the admin opened it; "both" describes the need
    case = await _ok(
        both, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    case = await _ok(both, case, "run_agent_step", step="1.2")
    r = await act(both, case, "complete_step", step="1.3")
    assert r.status_code == 409
    assert "whoever did 1.1" in r.json()["detail"]["message"]


async def test_a_failed_agent_is_recorded_and_can_be_rerun(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    case = await _open(req, snapshot)
    case = await _ok(
        req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    AGENT.fail = "Budget data is older than 24 hours"
    case = await _ok(req, case, "run_agent_step", step="1.2")
    assert step(case, "1.2")["status"] == "failed"
    assert step(case, "1.2")["l5"][0]["note"] == "Budget data is older than 24 hours"
    assert any("Failed step(s)" in b for b in case["blockers"])

    AGENT.fail = None
    case = await _ok(req, case, "run_agent_step", step="1.2")
    assert step(case, "1.2")["status"] == "done"


async def test_a_query_sends_the_request_back_and_voids_the_approval(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER)
    case = await _open(req, snapshot)
    case = await _ok(
        req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    case = await _ok(req, case, "run_agent_step", step="1.2")
    case = await _ok(owner, case, "complete_step", step="1.3")
    case = await _ok(owner, case, "approve")
    assert case["status"] == "approved"

    case = await _ok(owner, case, "redo_step", step="1.1", reason="Which lab is this for?")
    assert case["status"] == "draft"
    assert [step(case, k)["status"] for k in ("1.1", "1.2", "1.3", "1.4")] == ["pending"] * 4
    assert case["approvals"][0]["valid"] is False


async def test_a_rule_blocks_approval_with_its_reason(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER)
    case = await _open(req, snapshot)
    case = await _ok(
        req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 5000}}
    )
    case = await _ok(req, case, "run_agent_step", step="1.2")
    case = await _ok(owner, case, "complete_step", step="1.3")
    assert case["blockers"] == ["Quantities above 1000 need a framework contract."]
    assert (await act(owner, case, "approve")).status_code == 409


async def test_a_step_that_applies_waits_for_its_capacity(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER)
    _, buyer = await person("buyer@example.com", Cap.BUYER)
    case = await _open(req, snapshot, amount=5000)
    case = await _ok(
        req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    case = await _ok(req, case, "run_agent_step", step="1.2")
    case = await _ok(owner, case, "complete_step", step="1.3")
    assert step(case, "1.4")["status"] == "pending"
    case = await _ok(
        buyer, case, "complete_step", step="1.4", results={"1.4.a": {"note": "3 quotes"}}
    )
    assert step(case, "1.4")["l5"][0]["result"] == {"note": "3 quotes"}


async def test_people_see_their_own_cases_and_viewers_see_all(
    person: PersonFn, snapshot: dict[str, Any], entity: LegalEntity, demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    _, other = await person("req2@example.com", Cap.REQUESTER)
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER, entity=entity)
    case = await _open(req, snapshot)

    assert (await other.get(f"/api/v1/finance/cases/{case['id']}")).status_code == 404
    assert (await other.get("/api/v1/finance/cases")).json() == []
    assert (await act(other, case, "complete_step", step="1.1")).status_code == 404
    assert (await owner.get(f"/api/v1/finance/cases/{case['id']}")).status_code == 200
    assert [c["id"] for c in (await owner.get("/api/v1/finance/cases")).json()] == [case["id"]]


async def test_opening_needs_an_opener_capacity(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER)
    r = await open_demo(owner, snapshot)
    assert r.status_code == 409
    assert "capacity that may open one" in r.json()["detail"]["message"]


async def test_the_dashboard_queues_what_waits_on_me(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    _, owner = await person("bo@example.com", Cap.BUDGET_OWNER)
    case = await _open(req, snapshot)

    board = (await req.get("/api/v1/finance/dashboard")).json()
    assert [(i["reference"], i["step_key"]) for i in board["my_queue"]] == [
        (case["reference"], "1.1")
    ]
    assert board["workflows"][0]["open"] == 1
    assert board["workflows"][0]["measures"] == [
        {"id": "DEMO.M1", "label": "Cases", "unit": "count", "value": "1"}
    ]
    assert (await owner.get("/api/v1/finance/dashboard")).json()["my_queue"] == []

    case = await _ok(
        req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    case = await _ok(req, case, "run_agent_step", step="1.2")
    queue = (await owner.get("/api/v1/finance/dashboard")).json()["my_queue"]
    assert [i["step_key"] for i in queue] == ["1.3"]


async def test_the_audit_trail_names_each_step(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any, db: AsyncSession
) -> None:
    _, req = await person("req@example.com", Cap.REQUESTER)
    case = await _open(req, snapshot)
    await _ok(
        req, case, "complete_step", step="1.1", results={"1.1.a": {"item": "x", "quantity": 1}}
    )
    details = list(
        await db.scalars(
            select(AuditEvent.details).where(AuditEvent.event_type == "pod.case_complete_step")
        )
    )
    assert [d["summary"] for d in details] == [
        f"{case['reference']}: Step 1.1 Describe the need: done"
    ]


async def test_an_admin_sees_who_can_do_a_step_and_does_it_as_them(
    person: PersonFn, snapshot: dict[str, Any], demo_flow: Any, admin: AsyncClient,
    db: AsyncSession,
) -> None:  # fmt: skip
    """Testing a workflow: a requester who is also a budget owner opened it, so segregation of
    duties keeps them from approving; the admin opens a tab as the other budget owner and
    approves there."""
    _, req = await person("req@example.com", Cap.REQUESTER, Cap.BUDGET_OWNER)
    other, _ = await person("bo@example.com", Cap.BUDGET_OWNER)
    case = await _open(req, snapshot)
    case = await _ok(req, case, "complete_step", step="1.1",
                     results={"1.1.a": {"item": "Pipettes", "quantity": 20}})  # fmt: skip
    case = await _ok(req, case, "run_agent_step", step="1.2")

    r = await admin.get(f"/api/v1/finance/cases/{case['id']}/people", params={"step": "1.3"})
    assert r.status_code == 200, r.text
    people = {p["email"]: p["blocked"] for p in r.json()}
    assert people["bo@example.com"] is None
    assert "someone other than" in people["req@example.com"]
    r = await req.get(f"/api/v1/finance/cases/{case['id']}/people", params={"step": "1.3"})
    assert r.status_code == 403

    tab = {"X-Session-Slot": "botab12345"}
    body = {"user_id": str(other.id), "slot": "botab12345"}
    r = await admin.post("/api/v1/auth/act-as", json=body)
    assert r.status_code == 200
    r = await admin.post(
        f"/api/v1/finance/cases/{case['id']}/actions", headers=tab,
        json={"action": "complete_step", "expected_version": case["version"],
              "payload": {"step": "1.3"}},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    assert step(r.json(), "1.3")["l5"][0]["done_by"] == "Bo"
    done = [  # their own sign-in (the fixture's) aside
        e for e in await db.scalars(select(AuditEvent))
        if e.actor_id == other.id and not e.event_type.startswith("auth.")
    ]  # fmt: skip
    assert done
    assert all(e.details.get("acted_by") for e in done)
