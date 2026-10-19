from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentAssignment
from src.app.audit.models import AuditEvent
from src.app.auth.models import RefreshToken, User, UserRole
from tests.conftest import DEFAULT_PASSWORD, ClientFactory, MakeUser

USERS = "/api/v1/users"
LOGIN = "/api/v1/auth/login"
NEW_PASSWORD = "Another-Long-Password-2"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def adm(admin: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin)


async def create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "email": "New.Analyst@Example.com",
        "full_name": "New Analyst",
        "password": DEFAULT_PASSWORD,
        "assignments": [{"agent_key": "ap_invoice", "capacity": "preparer"}],
        **overrides,
    }
    r = await client.post(USERS, json=body)
    assert r.status_code == 201, r.text
    result: dict[str, Any] = r.json()
    return result


async def test_only_admins_can_manage_users(
    make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    c = await signed_in_client(await make_user("plain@example.com"))
    assert (await c.get(USERS)).status_code == 403
    r = await c.post(USERS, json={"email": "x@example.com", "full_name": "X", "password": "x" * 12})
    assert r.status_code == 403


async def test_create_list_and_sign_in(adm: AsyncClient, client: AsyncClient) -> None:
    user = await create(adm)
    assert user["email"] == "new.analyst@example.com"
    assert user["role"] == "user"
    assert [(a["agent_key"], a["capacity"]) for a in user["assignments"]] == [
        ("ap_invoice", "preparer")
    ]

    listed = (await adm.get(USERS, params={"search": "analyst"})).json()
    assert [u["email"] for u in listed] == ["new.analyst@example.com"]

    r = await client.post(LOGIN, json={"email": user["email"], "password": DEFAULT_PASSWORD})
    assert r.status_code == 200
    agents = (await client.get("/api/v1/agents")).json()
    assert [(a["key"], a["my_capacities"]) for a in agents] == [("ap_invoice", ["preparer"])]


async def test_create_validates_input(adm: AsyncClient) -> None:
    await create(adm)
    dup = await adm.post(
        USERS,
        json={"email": "new.analyst@example.com", "full_name": "Dup", "password": DEFAULT_PASSWORD},
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "email_taken"

    short = await adm.post(
        USERS, json={"email": "s@example.com", "full_name": "S", "password": "short"}
    )
    assert short.status_code == 422

    unknown = await adm.post(
        USERS,
        json={
            "email": "u@example.com",
            "full_name": "U",
            "password": DEFAULT_PASSWORD,
            "assignments": [{"agent_key": "nope", "capacity": "preparer"}],
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "unknown_agent"


async def test_update_and_assignments(adm: AsyncClient, db: AsyncSession) -> None:
    user = await create(adm)
    r = await adm.patch(f"{USERS}/{user['id']}", json={"full_name": "Renamed", "role": "user"})
    assert r.json()["full_name"] == "Renamed"

    r = await adm.put(
        f"{USERS}/{user['id']}/assignments",
        json={
            "assignments": [
                {"agent_key": "ap_invoice", "capacity": "reviewer"},
                {"agent_key": "expense_audit", "capacity": "preparer"},
                {"agent_key": "expense_audit", "capacity": "preparer"},  # duplicates collapse
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert [(a["agent_key"], a["capacity"]) for a in r.json()["assignments"]] == [
        ("ap_invoice", "reviewer"),
        ("expense_audit", "preparer"),
    ]
    rows = await db.scalars(select(AgentAssignment).where(AgentAssignment.user_id == user["id"]))
    assert len(list(rows)) == 2


async def test_password_reset_unlocks_and_signs_out(
    adm: AsyncClient, client: AsyncClient, db: AsyncSession
) -> None:
    user = await create(adm)
    assert (
        await client.post(LOGIN, json={"email": user["email"], "password": DEFAULT_PASSWORD})
    ).status_code == 200

    r = await adm.post(f"{USERS}/{user['id']}/password", json={"password": NEW_PASSWORD})
    assert r.status_code == 200
    tokens = await db.scalars(select(RefreshToken).where(RefreshToken.user_id == user["id"]))
    assert all(t.revoked_at is not None for t in tokens)

    old = await client.post(LOGIN, json={"email": user["email"], "password": DEFAULT_PASSWORD})
    assert old.status_code == 401
    new = await client.post(LOGIN, json={"email": user["email"], "password": NEW_PASSWORD})
    assert new.status_code == 200

    event = await db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "user.password_reset")
    )
    assert event is not None
    assert "password" not in event.details


async def test_deactivated_user_is_signed_out(adm: AsyncClient, client: AsyncClient) -> None:
    user = await create(adm)
    await client.post(LOGIN, json={"email": user["email"], "password": DEFAULT_PASSWORD})
    r = await adm.patch(f"{USERS}/{user['id']}", json={"is_active": False})
    assert r.json()["is_active"] is False
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_admin_cannot_lock_themselves_out(admin: User, adm: AsyncClient) -> None:
    for body in ({"is_active": False}, {"role": "user"}):
        r = await adm.patch(f"{USERS}/{admin.id}", json=body)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "self_management"
    assert (await adm.delete(f"{USERS}/{admin.id}")).status_code == 409


async def test_delete_only_without_history(adm: AsyncClient, db: AsyncSession) -> None:
    user = await create(adm)
    assert (await adm.delete(f"{USERS}/{user['id']}")).status_code == 204
    assert (await adm.get(f"{USERS}/{user['id']}")).status_code == 404
    assert await db.scalar(select(AuditEvent).where(AuditEvent.event_type == "user.deleted"))


async def test_user_with_runs_cannot_be_deleted(adm: AsyncClient, client: AsyncClient) -> None:
    user = await create(adm)
    await client.post(LOGIN, json={"email": user["email"], "password": DEFAULT_PASSWORD})
    assert (await client.post("/api/v1/agents/ap_invoice/runs")).status_code == 201

    r = await adm.delete(f"{USERS}/{user['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "user_has_history"
