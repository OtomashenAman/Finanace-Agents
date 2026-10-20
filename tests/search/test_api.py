from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole
from tests.agent_catalog.test_runs_api import PDF_EXAMPLE, assign, new_run
from tests.conftest import ClientFactory, MakeUser

SEARCH = "/api/v1/search"

pytestmark = pytest.mark.usefixtures("synced_agents")


async def hits(client: AsyncClient, q: str) -> list[dict[str, Any]]:
    r = await client.get(SEARCH, params={"q": q})
    assert r.status_code == 200, r.text
    found: list[dict[str, Any]] = r.json()["hits"]
    return found


async def test_search_finds_runs_by_reference_and_business_reference(
    make_user: MakeUser, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    me = await signed_in_client(user)
    run = await new_run(me, PDF_EXAMPLE)

    by_invoice = await hits(me, "inv-2048")
    assert [(h["kind"], h["title"]) for h in by_invoice] == [
        ("run", f"{run['reference']} · INV-2048")
    ]
    assert by_invoice[0]["link"] == f"/catalog/ap_invoice/runs/{run['id']}"
    number = str(int(run["reference"].removeprefix("RUN-")))
    assert [h["kind"] for h in await hits(me, number)] == ["run"]
    assert [h["kind"] for h in await hits(me, "invoice")] == ["agent"]
    assert await hits(me, "x") == []  # too short
    assert all(h["kind"] != "user" for h in await hits(me, "example.com"))

    other = await make_user("other@example.com")
    await assign(db, other, AgentCapacity.PREPARER)
    assert await hits(await signed_in_client(other), "inv-2048") == []

    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    assert [h["kind"] for h in await hits(admin, "inv-2048")] == ["run"]
    people = [h["subtitle"] for h in await hits(admin, "example.com") if h["kind"] == "user"]
    assert sorted(people) == ["admin@example.com", "ap.analyst@example.com", "other@example.com"]
