import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.service import sync_registry
from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from tests.conftest import ClientFactory, MakeUser

AGENTS = "/api/v1/agents"
SUMMARY = "/api/v1/overview/summary"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def preparer(make_user: MakeUser) -> User:
    return await make_user("ap.analyst@example.com", UserRole.PREPARER)


async def assign(db: AsyncSession, user: User, key: str, capacity: AgentCapacity) -> None:
    agent = await db.scalar(select(Agent).where(Agent.key == key))
    assert agent is not None
    db.add(AgentAssignment(user_id=user.id, agent_id=agent.id, capacity=capacity))
    await db.commit()


async def active_agents_kpi(client: AsyncClient) -> int:
    r = await client.get(SUMMARY)
    assert r.status_code == 200
    return int(r.json()["kpis"]["active_agents"])


# --- listing ------------------------------------------------------------------------------


async def test_catalog_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get(AGENTS)).status_code == 401


async def test_admin_sees_all_12_agents_in_catalog_order(
    admin: User, signed_in_client: ClientFactory
) -> None:
    c = await signed_in_client(admin)
    r = await c.get(AGENTS)

    assert r.status_code == 200
    agents = r.json()
    assert [a["code"] for a in agents] == [f"{n:02d}" for n in range(1, 13)]
    first = agents[0]
    assert first["key"] == "ap_invoice"
    assert first["name"] == "AP Invoice Intake, Coding & Approval"
    assert first["primary_user"] == "AP Analyst"
    assert first["reviewer"] == "AP Approver"
    assert first["is_active"] is True
    assert first["my_capacities"] == []


async def test_preparer_sees_only_assigned_active_agents(
    preparer: User, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    c = await signed_in_client(preparer)
    assert (await c.get(AGENTS)).json() == []

    await assign(db, preparer, "ap_invoice", AgentCapacity.PREPARER)
    await assign(db, preparer, "expense_audit", AgentCapacity.REVIEWER)
    agents = (await c.get(AGENTS)).json()
    assert [(a["key"], a["my_capacities"]) for a in agents] == [
        ("ap_invoice", ["preparer"]),
        ("expense_audit", ["reviewer"]),
    ]

    # A disabled agent disappears for non-admins even when assigned
    await db.execute(update(Agent).where(Agent.key == "expense_audit").values(is_active=False))
    await db.commit()
    assert [a["key"] for a in (await c.get(AGENTS)).json()] == ["ap_invoice"]


async def test_get_agent_hides_unassigned_agents_from_non_admins(
    preparer: User, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    c = await signed_in_client(preparer)
    assert (await c.get(f"{AGENTS}/treasury_cash")).status_code == 404

    await assign(db, preparer, "treasury_cash", AgentCapacity.PREPARER)
    r = await c.get(f"{AGENTS}/treasury_cash")
    assert r.status_code == 200
    assert r.json()["name"] == "Treasury Cash Forecasting & Liquidity"


async def test_unknown_agent_is_404(admin: User, signed_in_client: ClientFactory) -> None:
    c = await signed_in_client(admin)
    r = await c.get(f"{AGENTS}/does_not_exist")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "agent_not_found"


# --- admin toggle reflects on the overview ------------------------------------------------


async def test_admin_toggle_is_reflected_on_overview(
    admin: User, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    c = await signed_in_client(admin)
    assert await active_agents_kpi(c) == 12

    r = await c.patch(f"{AGENTS}/lease_accounting", json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert await active_agents_kpi(c) == 11

    # Admin still sees the disabled agent in the catalog (to re-enable it)
    lease = next(a for a in (await c.get(AGENTS)).json() if a["key"] == "lease_accounting")
    assert lease["is_active"] is False

    await c.patch(f"{AGENTS}/lease_accounting", json={"is_active": True})
    assert await active_agents_kpi(c) == 12

    events = list(await db.scalars(select(AuditEvent.event_type).order_by(AuditEvent.created_at)))
    assert events[-2:] == ["agent.deactivated", "agent.activated"]


async def test_toggle_requires_finance_admin(
    preparer: User, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    await assign(db, preparer, "ap_invoice", AgentCapacity.PREPARER)
    c = await signed_in_client(preparer)
    r = await c.patch(f"{AGENTS}/ap_invoice", json={"is_active": False})
    assert r.status_code == 403


# --- registry sync ------------------------------------------------------------------------


async def test_sync_is_idempotent(db: AsyncSession) -> None:
    result = await sync_registry(db)
    assert (result.created, result.updated, result.retired) == ([], [], [])


async def test_sync_restores_code_owned_fields_but_keeps_admin_state(db: AsyncSession) -> None:
    await db.execute(
        update(Agent).where(Agent.key == "ap_invoice").values(name="Renamed", is_active=False)
    )
    await db.commit()

    result = await sync_registry(db)
    await db.commit()

    agent = await db.scalar(select(Agent).where(Agent.key == "ap_invoice"))
    assert agent is not None
    await db.refresh(agent)
    assert result.updated == ["ap_invoice"]
    assert agent.name == "AP Invoice Intake, Coding & Approval"  # code wins
    assert agent.is_active is False  # admin decision kept


async def test_agent_removed_from_registry_is_retired_not_deleted(
    admin: User, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    db.add(
        Agent(
            key="legacy_agent",
            code="99",
            name="Legacy",
            short_name="Legacy",
            description="No longer in code",
            primary_user="x",
            reviewer="y",
            sort_order=99,
        )
    )
    await db.commit()

    result = await sync_registry(db)
    await db.commit()

    assert result.retired == ["legacy_agent"]
    assert await db.scalar(select(Agent).where(Agent.key == "legacy_agent")) is not None
    c = await signed_in_client(admin)
    assert "legacy_agent" not in [a["key"] for a in (await c.get(AGENTS)).json()]
    assert (await c.patch(f"{AGENTS}/legacy_agent", json={"is_active": True})).status_code == 404
    assert await active_agents_kpi(c) == 12
