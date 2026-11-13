"""Areas: which parts of the app (Agent Catalog, Service POD, Finance POD) each person has."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from tests.conftest import DEFAULT_PASSWORD, ClientFactory, MakeUser

USERS = "/api/v1/users"
ME = "/api/v1/auth/me"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def adm(make_user: MakeUser, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))


async def test_new_accounts_get_everything_their_role_allows(
    adm: AsyncClient, make_user: MakeUser
) -> None:
    assert (await adm.get(ME)).json()["areas"] == ["agent_catalog", "service_pod", "finance_pod"]
    plain = await make_user("plain@example.com")
    assert plain.areas == ["agent_catalog"]

    body = {"full_name": "A", "password": DEFAULT_PASSWORD}
    user = (await adm.post(USERS, json={**body, "email": "u@example.com"})).json()
    assert user["areas"] == ["agent_catalog"]
    admin = (
        await adm.post(USERS, json={**body, "email": "a@example.com", "role": "finance_admin"})
    ).json()
    assert admin["areas"] == ["agent_catalog", "service_pod", "finance_pod"]


async def test_the_pods_are_for_finance_admins_only(adm: AsyncClient) -> None:
    r = await adm.post(
        USERS,
        json={
            "email": "u@example.com",
            "full_name": "U",
            "password": DEFAULT_PASSWORD,
            "areas": ["agent_catalog", "finance_pod"],
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "area_not_allowed"


async def test_a_finance_pod_only_admin_sees_only_the_finance_pod(
    adm: AsyncClient, db: AsyncSession, client: AsyncClient
) -> None:
    created = (
        await adm.post(
            USERS,
            json={
                "email": "fp@example.com",
                "full_name": "Finance POD only",
                "password": DEFAULT_PASSWORD,
                "role": "finance_admin",
                "areas": ["finance_pod"],
            },
        )
    ).json()
    assert created["areas"] == ["finance_pod"]
    r = await client.post(
        "/api/v1/auth/login", json={"email": "fp@example.com", "password": DEFAULT_PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["areas"] == ["finance_pod"]

    assert (await client.get("/api/v1/finance-pod/overview")).status_code == 200
    assert (await client.get("/api/v1/pod/cases")).status_code == 403
    assert (await client.get("/api/v1/agents")).json() == []
    assert (await client.get("/api/v1/agents/ap_invoice")).status_code == 404

    # Given the Service POD later: it opens; the change is audited
    r = await adm.patch(f"{USERS}/{created['id']}", json={"areas": ["service_pod", "finance_pod"]})
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/pod/cases")).status_code == 200
    event = await db.scalar(
        select(AuditEvent)
        .where(AuditEvent.event_type == "user.updated")
        .order_by(AuditEvent.seq.desc())
    )
    assert event is not None and event.details["areas"] == ["service_pod", "finance_pod"]


async def test_demoting_an_admin_takes_the_pods_away(adm: AsyncClient, db: AsyncSession) -> None:
    created = (
        await adm.post(
            USERS,
            json={
                "email": "a@example.com",
                "full_name": "A",
                "password": DEFAULT_PASSWORD,
                "role": "finance_admin",
            },
        )
    ).json()
    r = await adm.patch(f"{USERS}/{created['id']}", json={"role": "user"})
    assert r.json()["areas"] == ["agent_catalog"]
    user = await db.scalar(select(User).where(User.email == "a@example.com"))
    assert user is not None and user.areas == ["agent_catalog"]
