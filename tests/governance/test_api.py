from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import User, UserRole
from tests.agent_catalog.test_runs_api import PDF_EXAMPLE, RUNS, act, analyzed_run, assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

GOV = "/api/v1/admin/governance"
MATCHING = {**PDF_EXAMPLE, "received_amount": "12500.00"}  # invoice total 12,500

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def adm(admin: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin)


@pytest.fixture
async def admin2(make_user: MakeUser) -> User:
    return await make_user("second.admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def adm2(admin2: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin2)


@pytest.fixture
async def me(make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory) -> AsyncClient:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return await signed_in_client(user)


async def submitted(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    return await act(client, await analyzed_run(client, **{**MATCHING, **overrides}), "submit")


async def review(client: AsyncClient, run: dict[str, Any], decision: str = "approved") -> Any:
    return await client.post(
        f"{RUNS}/{run['id']}/reviews", json={"decision": decision, "comment": "Checked it"}
    )


# --- maker-checker setting -------------------------------------------------------------------


async def test_self_approval_can_be_turned_off(
    adm: AsyncClient, adm2: AsyncClient, me: AsyncClient, fake_llm: FakeLLM
) -> None:
    assert (await me.get(f"{GOV}/settings")).status_code == 403
    assert (await adm.get(f"{GOV}/settings")).json()["allow_admin_self_approval"] is True

    own = await submitted(adm)
    assert own["permissions"]["can_review"] is True  # allowed by default

    r = await adm.put(f"{GOV}/settings", json={"allow_admin_self_approval": False})
    assert r.json()["allow_admin_self_approval"] is False
    seen = (await adm.get(f"{RUNS}/{own['id']}")).json()
    assert seen["permissions"]["can_review"] is False
    assert "segregation of duties" in seen["permissions"]["review_blocked_reason"]
    assert (await review(adm, own)).status_code == 403
    assert (await review(adm2, own)).json()["status"] == "approved"  # another admin may


# --- thresholds -------------------------------------------------------------------------------


async def test_thresholds_are_versioned_and_applied(
    adm: AsyncClient, me: AsyncClient, fake_llm: FakeLLM
) -> None:
    policies = (await adm.get(f"{GOV}/policies")).json()
    [policy] = [p for p in policies if p["agent_key"] == "ap_invoice"]
    assert [f["name"] for f in policy["fields"]] == [
        "po_tolerance",
        "receipt_tolerance",
        "high_value_amount",
    ]
    assert policy["current"]["version_label"] == "ap_invoice/v1"
    assert policy["current"]["is_default"] is True

    before = await analyzed_run(me, **{**MATCHING, "po_authorized_amount": "12490.00"})
    assert "PO_MISMATCH" in {f["code"] for f in before["flags"]}
    assert before["policy_version"] == "ap_invoice/v1"

    values = {"po_tolerance": "25.00", "receipt_tolerance": "0", "high_value_amount": "10000"}
    saved = (
        await adm.put(f"{GOV}/policies/ap_invoice", json={"values": values, "note": "Q4"})
    ).json()
    assert saved["current"]["version_label"] == "ap_invoice/v2"
    assert saved["current"]["created_by"] == "Admin"

    after = await analyzed_run(me, **{**MATCHING, "po_authorized_amount": "12490.00"})
    flags = {f["code"]: f["message"] for f in after["flags"]}
    assert "within the 25.00 PO tolerance" in flags["PO_MATCH"]
    assert "HIGH_VALUE_INVOICE" in flags
    assert after["policy_version"] == "ap_invoice/v2"
    assert after["policy_values"]["po_tolerance"] == "25.00"
    # The earlier run keeps the version it was analyzed with
    assert (await me.get(f"{RUNS}/{before['id']}")).json()["policy_version"] == "ap_invoice/v1"

    same = await adm.put(f"{GOV}/policies/ap_invoice", json={"values": values})
    assert same.json()["current"]["version_label"] == "ap_invoice/v2"  # nothing changed
    bad = await adm.put(f"{GOV}/policies/ap_invoice", json={"values": {"po_tolerance": "-1"}})
    assert bad.status_code == 422
    unknown = await adm.put(f"{GOV}/policies/ap_invoice", json={"values": {"nope": "1"}})
    assert unknown.status_code == 422

    history = (await adm.get(f"{GOV}/policies/ap_invoice/versions")).json()
    assert [(h["version_label"], h["note"]) for h in history] == [
        ("ap_invoice/v2", "Q4"),
        ("ap_invoice/v1", "Defaults defined with the agent"),
    ]
    assert (await me.get(f"{GOV}/policies")).status_code == 403
    assert (await adm.get(f"{GOV}/policies/lease_accounting/versions")).status_code == 404


# --- approval matrix --------------------------------------------------------------------------


async def test_matrix_validation(adm: AsyncClient, admin: User, me: AsyncClient) -> None:
    tiers = [
        {"min_amount": "0", "approvals_required": 1},
        {"min_amount": "0.00", "approvals_required": 1},
    ]
    r = await adm.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    assert "different starting amount" in r.json()["detail"]["message"]
    r = await adm.put(
        f"{GOV}/approval-matrix/ap_invoice",
        json={"tiers": [{"min_amount": "0", "approvals_required": 2}]},  # only one admin exists
    )
    assert "only 1 Finance Admin" in r.json()["detail"]["message"]
    r = await adm.put(
        f"{GOV}/approval-matrix/ap_invoice",
        json={
            "tiers": [{"min_amount": "0", "approvals_required": 1, "approver_ids": [str(admin.id)]}]
        },
    )
    assert r.status_code == 200
    assert r.json()["tiers"][0]["approvers"][0]["full_name"] == "Admin"
    assert r.json()["amount_label"] == "Invoice total"
    assert (
        await me.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": []})
    ).status_code == 403


async def test_high_amounts_need_two_different_approvers(
    adm: AsyncClient, adm2: AsyncClient, me: AsyncClient, fake_llm: FakeLLM
) -> None:
    tiers = [
        {"min_amount": "0", "approvals_required": 1},
        {"min_amount": "10000", "approvals_required": 2},
    ]
    assert (
        await adm.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    ).status_code == 200

    small = await submitted(
        me, invoice_total="500.00", po_authorized_amount="500.00", received_amount="500.00"
    )
    assert small["approval"]["required"] == 1

    big = await submitted(me)  # 12,500
    assert big["approval"] == {
        "required": 2,
        "received": 0,
        "approvers": [],
        "amount": "12500.00",
        "tier_min_amount": "10000.00",
        "approved_by": [],
    }
    first = (await review(adm, big)).json()
    assert first["status"] == "pending_approval"
    assert first["approval"]["received"] == 1
    again = await review(adm, big)
    assert again.status_code == 403
    assert "another approver" in again.json()["detail"]["message"]

    done = (await review(adm2, big)).json()
    assert done["status"] == "approved"
    assert [p["full_name"] for p in done["approval"]["approved_by"]] == ["Admin", "Second Admin"]


async def test_rejection_ends_a_multi_approval_round_and_resubmit_starts_over(
    adm: AsyncClient, adm2: AsyncClient, me: AsyncClient, fake_llm: FakeLLM
) -> None:
    tiers = [{"min_amount": "0", "approvals_required": 2}]
    await adm.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    run = await submitted(me)
    await review(adm, run)
    back = (await review(adm2, run, "changes_requested")).json()
    assert back["status"] == "changes_requested"

    run = await act(me, await act(me, back, "analyze"), "submit")
    assert run["approval"]["received"] == 0  # a new round
    assert (await review(adm, run)).json()["status"] == "pending_approval"


async def test_tier_approvers_are_restricted(
    adm: AsyncClient, adm2: AsyncClient, admin2: User, me: AsyncClient, fake_llm: FakeLLM
) -> None:
    tiers = [{"min_amount": "0", "approvals_required": 1, "approver_ids": [str(admin2.id)]}]
    await adm.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    run = await submitted(me)
    assert [p["full_name"] for p in run["approval"]["approvers"]] == ["Second Admin"]
    seen = (await adm.get(f"{RUNS}/{run['id']}")).json()
    assert seen["permissions"]["can_review"] is False
    assert (await review(adm, run)).status_code == 403
    assert (await review(adm2, run)).json()["status"] == "approved"


# --- overview filters -------------------------------------------------------------------------


async def test_overview_filters_by_agent_and_priority(
    adm: AsyncClient, me: AsyncClient, fake_llm: FakeLLM
) -> None:
    await act(me, await analyzed_run(me), "submit")  # receipt mismatch: high priority
    await submitted(me, invoice_number="INV-OK")  # clean: normal
    summary = "/api/v1/overview/summary"
    assert (await adm.get(summary)).json()["kpis"]["pending_review"] == 2
    high = (await adm.get(summary, params={"priority": "high"})).json()
    assert (high["kpis"]["pending_review"], len(high["worklist"])) == (1, 1)
    normal = (await adm.get(summary, params={"priority": "normal"})).json()
    assert normal["kpis"]["high_priority"] == 0
    other_agent = (await adm.get(summary, params={"agent": "expense_audit"})).json()
    assert other_agent["kpis"]["pending_review"] == 0
    assert (await adm.get(summary, params={"agent": "ap_invoice"})).json()["kpis"][
        "pending_review"
    ] == 2
