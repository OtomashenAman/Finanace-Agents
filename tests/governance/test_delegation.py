from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.governance.test_api import GOV, review, submitted

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def me(make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory) -> AsyncClient:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return await signed_in_client(user)


@pytest.fixture
async def approver(make_user: MakeUser) -> User:
    return await make_user("approver@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def deputy(make_user: MakeUser) -> User:
    return await make_user("deputy@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def appr(approver: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(approver)


@pytest.fixture
async def dep(deputy: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(deputy)


def period(days: int = 7) -> dict[str, str]:
    now = utcnow()
    return {
        "starts_at": (now - timedelta(minutes=1)).isoformat(),
        "ends_at": (now + timedelta(days=days)).isoformat(),
    }


async def test_a_delegate_approves_for_a_named_approver(
    appr: AsyncClient,
    dep: AsyncClient,
    approver: User,
    deputy: User,
    me: AsyncClient,
    fake_llm: FakeLLM,
) -> None:
    tiers = [{"min_amount": "0", "approvals_required": 1, "approver_ids": [str(approver.id)]}]
    await appr.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    run = await submitted(me)
    assert (await review(dep, run)).status_code == 403  # not named, no delegation yet

    r = await appr.post(
        f"{GOV}/delegations", json={"delegate_id": str(deputy.id), "reason": "Leave", **period()}
    )
    assert r.status_code == 201, r.text
    assert r.json()["active"] is True
    assert (await dep.get(f"/api/v1/agents/ap_invoice/runs/{run['id']}")).json()["permissions"][
        "can_review"
    ] is True

    done = (await review(dep, run)).json()
    assert done["status"] == "approved"
    assert done["reviews"][0]["reviewer"]["full_name"] == "Deputy"
    assert done["reviews"][0]["on_behalf_of"]["full_name"] == "Approver"
    events = (await appr.get("/api/v1/audit-events", params={"run": run["reference"]})).json()
    assert f"Approved {run['reference']} on behalf of Approver" in {
        e["summary"] for e in events["items"]
    }


async def test_delegations_end_and_can_be_cancelled(
    appr: AsyncClient,
    dep: AsyncClient,
    approver: User,
    deputy: User,
    me: AsyncClient,
    fake_llm: FakeLLM,
) -> None:
    tiers = [{"min_amount": "0", "approvals_required": 1, "approver_ids": [str(approver.id)]}]
    await appr.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    delegation = (
        await appr.post(f"{GOV}/delegations", json={"delegate_id": str(deputy.id), **period()})
    ).json()
    cancelled = (await appr.post(f"{GOV}/delegations/{delegation['id']}/cancel")).json()
    assert cancelled["active"] is False
    run = await submitted(me)
    assert (await review(dep, run)).status_code == 403


async def test_delegation_rules(
    appr: AsyncClient, approver: User, deputy: User, me: AsyncClient
) -> None:
    def bad(body: dict[str, Any]) -> str:
        return str(body["detail"]["message"])

    same = await appr.post(f"{GOV}/delegations", json={"delegate_id": str(approver.id), **period()})
    assert "someone else" in bad(same.json())
    long = await appr.post(
        f"{GOV}/delegations", json={"delegate_id": str(deputy.id), **period(120)}
    )
    assert "90 days" in bad(long.json())
    now = utcnow()
    over = await appr.post(
        f"{GOV}/delegations",
        json={
            "delegate_id": str(deputy.id),
            "starts_at": (now - timedelta(days=3)).isoformat(),
            "ends_at": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert "already over" in bad(over.json())
    assert (await me.get(f"{GOV}/delegations")).status_code == 403


async def test_the_same_person_never_counts_twice(
    appr: AsyncClient,
    dep: AsyncClient,
    approver: User,
    deputy: User,
    me: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    third = await make_user("third@example.com", UserRole.FINANCE_ADMIN)
    tiers = [
        {
            "min_amount": "0",
            "approvals_required": 2,
            "approver_ids": [str(approver.id), str(third.id)],
        }
    ]
    await appr.put(f"{GOV}/approval-matrix/ap_invoice", json={"tiers": tiers})
    await appr.post(f"{GOV}/delegations", json={"delegate_id": str(deputy.id), **period()})
    run = await submitted(me)
    first = (await review(dep, run)).json()  # deputy, for the approver
    assert first["approval"]["received"] == 1
    again = await review(appr, run)  # the approver already counted through the deputy
    assert again.status_code == 403
    done = (await review(await signed_in_client(third), run)).json()
    assert done["status"] == "approved"
