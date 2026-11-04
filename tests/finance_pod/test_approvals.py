"""Phase 1.2: the budget agent's check and the budget owner's decision."""

from typing import Any

from httpx import AsyncClient

from src.app.auth.models import UserRole
from tests.conftest import ClientFactory, MakeUser
from tests.finance_pod.conftest import SHEETS, request_body, upload, workbook

BASE = "/api/v1/finance-pod/requests"


async def submitted(client: AsyncClient, **changes: Any) -> dict[str, Any]:
    r = await client.post(BASE, json=request_body(**changes))
    assert r.status_code == 201, r.text
    pr = r.json()
    r = await client.post(f"{BASE}/{pr['id']}/submit", json={"expected_version": pr["version"]})
    assert r.status_code == 200, r.text
    return r.json()


async def decide(
    client: AsyncClient, pr: dict[str, Any], decision: str, note: str = "", ack: bool = False
) -> Any:
    fresh = (await client.get(f"{BASE}/{pr['id']}")).json()
    return await client.post(
        f"{BASE}/{pr['id']}/decide",
        json={
            "expected_version": fresh["version"],
            "decision": decision,
            "note": note,
            "acknowledge_budget": ack,
        },
    )


def lines(*rows: tuple[str, str, str, str | None]) -> list[dict[str, Any]]:
    return [
        {"description": d, "quantity": q, "unit_price": p, "category": c} for d, q, p, c in rows
    ]


async def test_the_budget_agent_shows_the_impact_and_routes_to_the_budget_owner(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    pr = await submitted(fpod)
    check = pr["budget_check"]
    assert pr["round"] == 1
    [impact] = check["impacts"]
    # Grant GR-22's lab-supplies line: 80000 - 0 committed - 12000 spent
    assert (impact["holder"], impact["category"]) == ("grant GR-22", "lab supplies")
    assert (impact["available"], impact["this_request"], impact["remaining_after"]) == (
        "68000.00",
        "425.00",
        "67575.00",
    )
    assert check["findings"] == []
    # The cost centre's owner; the matrix's 0-tier names the same person, so one step
    assert [(s["capacity"], s["approver_email"], s["status"]) for s in pr["route"]] == [
        ("Budget owner", "budget@gia.example", "waiting")
    ]
    assert pr["can_decide"] is False
    assert pr["decide_blocker"] == "Waiting for Budget (Budget owner)."

    seen = (await other_admin.get(f"{BASE}/{pr['id']}")).json()
    assert seen["can_decide"] is True
    queue = await other_admin.get("/api/v1/finance-pod/approvals")
    assert [r["reference"] for r in queue.json()] == [pr["reference"]]
    assert (await fpod.get("/api/v1/finance-pod/approvals")).json() == []

    r = await decide(other_admin, pr, "approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["route"][0]["status"] == "approved"

    # The approved request now holds that budget for the next one
    nxt = await submitted(fpod)
    assert nxt["budget_check"]["impacts"][0]["approved_requests"] == "425.00"
    assert nxt["budget_check"]["impacts"][0]["available"] == "67575.00"

    # Cancelling the approved request frees it again
    await fpod.post(
        f"{BASE}/{pr['id']}/cancel",
        json={"expected_version": r.json()["version"], "reason": "No longer needed"},
    )
    rechecked = await other_admin.post(f"{BASE}/{nxt['id']}/budget-check")
    assert rechecked.json()["budget_check"]["impacts"][0]["approved_requests"] == "0.00"


async def test_the_requester_never_approves_their_own_request(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await submitted(
        fpod, cost_centre_code="CC-200", lab_code=None, project_code=None, grant_code=None
    )
    # CC-200's owner has no account: anyone but the requester may decide for them
    assert pr["route"][0]["approver_name"] is None
    r = await decide(fpod, pr, "approve", "fine", ack=True)
    assert r.status_code == 403
    assert "Nobody approves a request they raised" in r.json()["detail"]["message"]


async def test_over_budget_or_no_budget_needs_an_acknowledged_note(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    pr = await submitted(fpod, lines=lines(("Sequencer reagents", "1", "70000", "lab supplies")))
    [finding] = pr["budget_check"]["findings"]
    assert (finding["kind"], finding["severity"]) == ("over_budget", "acknowledge")
    assert finding["message"].endswith("budget of grant GR-22 (lab supplies) by 2,000.00 USD.")
    assert pr["budget_check"]["impacts"][0]["over_budget"] is True
    r = await decide(other_admin, pr, "approve")
    assert r.status_code == 422
    assert "Confirm you approve despite" in r.json()["detail"]["message"]
    r = await decide(other_admin, pr, "approve", "Dean agreed to cover from reserves", ack=True)
    assert r.status_code == 200, r.text
    [d] = r.json()["decisions"]
    assert (d["decision"], d["budget_acknowledged"], d["decided_by_name"]) == (
        "approve",
        True,
        "Budget",
    )


async def test_an_unallowable_grant_expense_blocks_approval(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    pr = await submitted(fpod, lines=lines(("Wine for the retreat", "6", "30", "alcohol")))
    blocking = [f for f in pr["budget_check"]["findings"] if f["severity"] == "blocking"]
    assert blocking[0]["message"] == "Line 1: grant GR-22 doesn't allow 'alcohol'."
    assert (await decide(other_admin, pr, "approve", "ok", ack=True)).status_code == 422
    assert (await decide(other_admin, pr, "reject")).status_code == 422  # needs a reason
    r = await decide(other_admin, pr, "reject", "Not allowable on this grant")
    assert r.json()["status"] == "rejected"
    assert r.json()["closed_at"] is not None


async def test_a_query_goes_back_to_the_requester_and_resubmitting_starts_a_new_round(
    fpod: AsyncClient, other_admin: AsyncClient, reference: None
) -> None:
    pr = await submitted(fpod)
    r = await decide(other_admin, pr, "query", "Which run is this for?")
    assert r.json()["status"] == "queried"
    assert r.json()["route"][0]["status"] == "queried"

    mine = (await fpod.get(f"{BASE}/{pr['id']}")).json()
    assert mine["can_edit"] is True
    r = await fpod.put(
        f"{BASE}/{pr['id']}",
        json={
            **request_body(purpose="Run 14 of the sequencing study"),
            "expected_version": mine["version"],
        },
    )
    r = await fpod.post(f"{BASE}/{pr['id']}/submit", json={"expected_version": r.json()["version"]})
    again = r.json()
    assert (again["status"], again["round"]) == ("submitted", 2)
    assert again["route"][0]["status"] == "waiting"
    assert [(d["round"], d["decision"]) for d in again["decisions"]] == [(1, "query")]


async def test_matrix_tiers_add_steps_and_an_admin_can_decide_for_someone_without_an_account(
    fpod: AsyncClient,
    other_admin: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    reference: None,
) -> None:
    matrix = {
        "Authority matrix": [
            *SHEETS["Authority matrix"],
            ["request", None, 100, "dean@gia.example", "Dean"],
            ["request", None, 50000, "provost@gia.example", "Provost"],
        ]
    }
    assert (await upload(fpod, workbook(matrix))).status_code == 200
    pr = await submitted(fpod)  # 425: budget owner, then the dean (not the provost)
    assert [s["capacity"] for s in pr["route"]] == ["Budget owner", "Dean"]

    assert (await decide(other_admin, pr, "approve")).status_code == 200
    # The dean has no account; the budget owner already decided a step, the requester raised it
    r = await decide(other_admin, pr, "approve")
    assert r.status_code == 403
    assert (await decide(fpod, pr, "approve")).status_code == 403

    third = await signed_in_client(
        await make_user("controller@gia.example", UserRole.FINANCE_ADMIN)
    )
    r = await decide(third, pr, "approve", "Dean on leave; approved for them")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["decisions"][-1]["acting_for"] == "dean@gia.example"


async def test_a_single_admin_can_self_approve_only_when_allowed_and_it_is_marked(
    fpod: AsyncClient, reference: None
) -> None:
    pr = await submitted(
        fpod, cost_centre_code="CC-200", lab_code=None, project_code=None, grant_code=None
    )
    await fpod.put(
        "/api/v1/finance-pod/settings",
        json={
            "currency": "USD",
            "purchasing_threshold": "10000",
            "min_quotes": 3,
            "allow_self_approval": True,
        },
    )
    r = await decide(fpod, pr, "approve", "Demo tenant, single admin", ack=True)
    assert r.status_code == 200, r.text
    assert r.json()["decisions"][0]["self_approval"] is True
    audit = await fpod.get("/api/v1/audit-events", params={"category": "finance_pod"})
    assert any("self-approval allowed" in e["summary"] for e in audit.json()["items"])
