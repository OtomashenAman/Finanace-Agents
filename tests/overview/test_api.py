import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.auth.models import UserRole
from tests.conftest import ClientFactory, MakeUser

SUMMARY = "/api/v1/overview/summary"

pytestmark = pytest.mark.usefixtures("synced_agents")


async def test_summary_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get(SUMMARY)).status_code == 401


async def test_admin_summary(make_user: MakeUser, signed_in_client: ClientFactory) -> None:
    c = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))

    r = await c.get(SUMMARY, params={"period": "2026-10"})

    assert r.status_code == 200
    assert r.json() == {
        "period": "2026-10",
        "entity": "All entities",
        "kpis": {
            "active_agents": 12,
            "runs_this_month": 0,
            "pending_review": 0,
            "high_priority": 0,
        },
        "worklist": [],
        "controls": {
            "entity": "All entities",
            "period_label": "October 2026",
            "review_sla_hours": 24,
            "connector_health": "Not configured",
            "model_execution": "Guarded",
        },
    }


async def test_period_defaults_to_current_month(
    make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    c = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    period = (await c.get(SUMMARY)).json()["period"]
    assert len(period) == 7
    assert period[4] == "-"


@pytest.mark.parametrize("period", ["2026-13", "2026-1", "october", "2026-10-01"])
async def test_invalid_period_is_rejected(
    period: str, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    c = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    assert (await c.get(SUMMARY, params={"period": period})).status_code == 422


async def test_non_admin_counts_only_own_agents_and_gets_no_admin_controls(
    make_user: MakeUser, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    preparer = await make_user("ap.analyst@example.com", UserRole.USER)
    for key in ("ap_invoice", "expense_audit"):
        agent = await db.scalar(select(Agent).where(Agent.key == key))
        assert agent is not None
        db.add(
            AgentAssignment(user_id=preparer.id, agent_id=agent.id, capacity=AgentCapacity.PREPARER)
        )
    await db.commit()

    body = (await (await signed_in_client(preparer)).get(SUMMARY)).json()

    assert body["kpis"]["active_agents"] == 2
    assert body["controls"] is None
