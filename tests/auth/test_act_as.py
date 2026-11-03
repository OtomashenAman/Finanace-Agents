"""A Finance Admin testing a workflow opens a tab as another user ("act as"): no password,
the admin's own tab untouched, and everything done in it audited as the admin's."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from src.app.core.config import get_settings
from tests.conftest import ClientFactory, MakeUser

ME, ACT_AS = "/api/v1/auth/me", "/api/v1/auth/act-as"
SLOT = "newtab12345"
NEW_TAB = {"X-Session-Slot": SLOT}


@pytest.fixture
async def admin_user(make_user: MakeUser) -> User:
    return await make_user("fa@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def admin(admin_user: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin_user)


async def test_an_admin_opens_a_tab_as_a_user(
    admin: AsyncClient, admin_user: User, make_user: MakeUser, db: AsyncSession
) -> None:
    ravi = await make_user("ravi@example.com")
    assert (await admin.get(ME)).json()["can_act_as"] is True

    r = await admin.post(ACT_AS, json={"user_id": str(ravi.id), "slot": SLOT})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "ravi@example.com"

    tab = (await admin.get(ME, headers=NEW_TAB)).json()
    assert tab["email"] == "ravi@example.com"
    assert tab["acted_by"]["email"] == "fa@example.com"
    assert tab["can_act_as"] is False
    own = (await admin.get(ME)).json()  # the admin's own tab is still the admin
    assert own["email"] == "fa@example.com"
    assert own["acted_by"] is None

    # a refreshed session stays the admin's
    assert (await admin.post("/api/v1/auth/refresh", headers=NEW_TAB)).status_code == 204
    assert (await admin.get(ME, headers=NEW_TAB)).json()["acted_by"]["email"] == "fa@example.com"

    # what's done in it says so, and the switch itself is audited
    r = await admin.post("/api/v1/auth/logout", headers=NEW_TAB)
    assert r.status_code == 204
    events = {e.event_type: e for e in await db.scalars(select(AuditEvent))}
    assert events["auth.act_as"].actor_id == admin_user.id
    assert events["auth.act_as"].details["user_id"] == str(ravi.id)
    assert events["auth.logout"].actor_id == ravi.id
    assert events["auth.logout"].details["acted_by"] == str(admin_user.id)


async def test_only_an_admin_acts_and_only_as_a_user(
    admin: AsyncClient, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    ravi = await make_user("ravi@example.com")
    other_admin = await make_user("fa2@example.com", UserRole.FINANCE_ADMIN)
    as_ravi = await signed_in_client(ravi)
    r = await as_ravi.post(ACT_AS, json={"user_id": str(other_admin.id), "slot": SLOT})
    assert r.status_code == 403
    r = await admin.post(ACT_AS, json={"user_id": str(other_admin.id), "slot": SLOT})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "act_as_refused"


async def test_a_tab_as_a_user_cant_change_their_password(
    admin: AsyncClient, make_user: MakeUser
) -> None:
    ravi = await make_user("ravi@example.com")
    await admin.post(ACT_AS, json={"user_id": str(ravi.id), "slot": SLOT})
    r = await admin.post(
        "/api/v1/auth/me/password",
        json={"current_password": "x", "new_password": "a-new-password-123"},
        headers=NEW_TAB,
    )
    assert r.status_code == 403


async def test_turned_off_it_refuses_and_ends_open_tabs(
    admin: AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    ravi = await make_user("ravi@example.com")
    await admin.post(ACT_AS, json={"user_id": str(ravi.id), "slot": SLOT})
    monkeypatch.setattr(get_settings(), "act_as_allowed", False)

    assert (await admin.get(ME)).json()["can_act_as"] is False
    r = await admin.post(ACT_AS, json={"user_id": str(ravi.id), "slot": SLOT})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "act_as_disabled"
    assert (await admin.post("/api/v1/auth/refresh", headers=NEW_TAB)).status_code == 401
