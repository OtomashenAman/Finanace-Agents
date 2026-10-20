import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import User, UserRole
from tests.agent_catalog.test_runs_api import PDF_EXAMPLE, RUNS, act, assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

ENTITIES = "/api/v1/entities"
USERS = "/api/v1/users"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def adm(admin: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin)


@pytest.fixture
async def analyst(make_user: MakeUser, db: AsyncSession) -> User:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return user


@pytest.fixture
async def me(analyst: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(analyst)


async def entity(adm: AsyncClient, code: str, name: str) -> dict[str, Any]:
    r = await adm.post(ENTITIES, json={"code": code, "name": name})
    assert r.status_code == 201, r.text
    result: dict[str, Any] = r.json()
    return result


async def give(adm: AsyncClient, user: User, *entities: dict[str, Any]) -> None:
    r = await adm.put(
        f"{USERS}/{user.id}/entities", json={"entity_ids": [e["id"] for e in entities]}
    )
    assert r.status_code == 200, r.text


async def test_admin_manages_entities(adm: AsyncClient, me: AsyncClient, analyst: User) -> None:
    us = await entity(adm, "us01", "US Operations")
    assert us["code"] == "US01" and us["is_active"] is True
    dup = await adm.post(ENTITIES, json={"code": "US01", "name": "Again"})
    assert dup.json()["detail"]["code"] == "entity_code_taken"
    assert (await adm.post(ENTITIES, json={"code": "bad code!", "name": "X"})).status_code == 422
    assert (await me.post(ENTITIES, json={"code": "UK01", "name": "UK"})).status_code == 403

    uk = await entity(adm, "UK01", "UK Operations")
    assert (await me.get(ENTITIES)).json() == []
    await give(adm, analyst, uk)
    assert [e["code"] for e in (await me.get(ENTITIES)).json()] == ["UK01"]
    assert [e["code"] for e in (await adm.get(ENTITIES)).json()] == ["UK01", "US01"]

    user = (await adm.get(f"{USERS}/{analyst.id}")).json()
    assert [e["code"] for e in user["entities"]] == ["UK01"]
    r = await adm.patch(f"{ENTITIES}/{us['id']}", json={"name": "US Ops", "is_active": False})
    assert (r.json()["name"], r.json()["is_active"]) == ("US Ops", False)


async def test_without_entities_runs_have_none(me: AsyncClient) -> None:
    run = (await me.post(RUNS)).json()
    assert run["entity"] is None


async def test_new_runs_need_an_assigned_active_entity(
    adm: AsyncClient, me: AsyncClient, analyst: User
) -> None:
    us = await entity(adm, "US01", "US Operations")
    r = await me.post(RUNS)
    assert r.json()["detail"]["code"] == "no_entities_assigned"

    await give(adm, analyst, us)
    run = (await me.post(RUNS)).json()  # the only one: picked automatically
    assert run["entity"] == {"id": us["id"], "code": "US01", "name": "US Operations"}

    uk = await entity(adm, "UK01", "UK Operations")
    await give(adm, analyst, us, uk)
    assert (await me.post(RUNS)).json()["detail"]["code"] == "entity_required"
    run = (await me.post(RUNS, json={"entity_id": uk["id"]})).json()
    assert run["entity"]["code"] == "UK01"

    de = await entity(adm, "DE01", "Germany")
    r = await me.post(RUNS, json={"entity_id": de["id"]})  # not assigned
    assert r.json()["detail"]["code"] == "entity_not_allowed"
    await adm.patch(f"{ENTITIES}/{uk['id']}", json={"is_active": False})
    r = await me.post(RUNS, json={"entity_id": uk["id"]})  # inactive
    assert r.json()["detail"]["code"] == "entity_not_allowed"

    # Admins may file for any active entity
    assert (await adm.post(RUNS, json={"entity_id": de["id"]})).json()["entity"]["code"] == "DE01"


async def test_users_only_see_runs_of_their_entities(
    adm: AsyncClient, me: AsyncClient, analyst: User
) -> None:
    us = await entity(adm, "US01", "US Operations")
    uk = await entity(adm, "UK01", "UK Operations")
    await give(adm, analyst, us, uk)
    us_run = (await me.post(RUNS, json={"entity_id": us["id"]})).json()
    uk_run = (await me.post(RUNS, json={"entity_id": uk["id"]})).json()

    await give(adm, analyst, us)  # UK taken away
    assert [r["id"] for r in (await me.get(RUNS)).json()] == [us_run["id"]]
    assert (await me.get(f"{RUNS}/{uk_run['id']}")).status_code == 404

    # Admin: everything, or filtered by entity
    assert len((await adm.get(RUNS)).json()) == 2
    only_uk = (await adm.get(RUNS, params={"entity_id": uk["id"]})).json()
    assert [r["id"] for r in only_uk] == [uk_run["id"]]


async def test_overview_and_approvals_filter_by_entity(
    adm: AsyncClient, me: AsyncClient, analyst: User, fake_llm: FakeLLM
) -> None:
    us = await entity(adm, "US01", "US Operations")
    uk = await entity(adm, "UK01", "UK Operations")
    await give(adm, analyst, us, uk)
    for e in (us, uk):
        run = (await me.post(RUNS, json={"entity_id": e["id"]})).json()
        await me.put(f"{RUNS}/{run['id']}/input", json={"values": PDF_EXAMPLE})
        await act(me, await act(me, run, "analyze"), "submit")

    summary = (await adm.get("/api/v1/overview/summary", params={"entity_id": us["id"]})).json()
    assert summary["entity"] == "US01 · US Operations"
    assert summary["controls"]["entity"] == "US01 · US Operations"
    assert summary["kpis"]["pending_review"] == 1
    assert summary["worklist"][0]["entity_code"] == "US01"
    assert (await adm.get("/api/v1/overview/summary")).json()["kpis"]["pending_review"] == 2

    queue = (await adm.get("/api/v1/approvals", params={"entity_id": uk["id"]})).json()
    assert [r["entity"]["code"] for r in queue] == ["UK01"]

    # A user can't filter by an entity they don't work for
    await give(adm, analyst, us)
    r = await me.get("/api/v1/overview/summary", params={"entity_id": uk["id"]})
    assert r.status_code == 404


async def test_the_ai_is_told_the_entity(
    adm: AsyncClient, me: AsyncClient, analyst: User, fake_llm: FakeLLM
) -> None:
    us = await entity(adm, "US01", "US Operations")
    await give(adm, analyst, us)
    run = (await me.post(RUNS)).json()
    await me.put(f"{RUNS}/{run['id']}/input", json={"values": PDF_EXAMPLE})
    await act(me, run, "analyze")
    assert json.loads(fake_llm.calls[-1][1])["legal_entity"] == "US Operations"


async def test_entity_changes_are_audited(adm: AsyncClient, analyst: User) -> None:
    us = await entity(adm, "US01", "US Operations")
    await give(adm, analyst, us)
    summaries = {e["summary"] for e in (await adm.get("/api/v1/audit-events")).json()["items"]}
    assert "Created legal entity US01 · US Operations" in summaries
    assert "Changed legal entities of Ap Analyst: US01" in summaries
