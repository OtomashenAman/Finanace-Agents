import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import User, UserRole
from tests.agent_catalog.test_runs_api import act, analyzed_run, assign, new_run
from tests.conftest import ClientFactory, FakeLLM, MakeUser

APPROVALS = "/api/v1/approvals"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def prep(
    make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory
) -> AsyncClient:
    user = await make_user("ap.analyst@example.com", UserRole.USER)
    await assign(db, user, AgentCapacity.PREPARER)
    return await signed_in_client(user)


async def test_approvals_queue_for_admin_and_own_submissions_for_users(
    make_user: MakeUser,
    db: AsyncSession,
    prep: AsyncClient,
    admin: User,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    mine = await act(prep, await analyzed_run(prep), "submit")
    await new_run(prep)  # drafts never show up
    other = await make_user("other.analyst@example.com", UserRole.USER)
    await assign(db, other, AgentCapacity.PREPARER)
    c = await signed_in_client(other)
    theirs = await act(c, await analyzed_run(c, invoice_number="OTH-1"), "submit")

    adm = await signed_in_client(admin)
    queue = (await adm.get(APPROVALS)).json()
    assert [r["id"] for r in queue] == [mine["id"], theirs["id"]]  # oldest first
    assert queue[0]["agent_key"] == "ap_invoice"
    assert queue[0]["submitted_at"] is not None
    assert [r["id"] for r in (await prep.get(APPROVALS)).json()] == [mine["id"]]

    await act(adm, mine, "reviews", decision="approved", comment="Looks right")
    assert [r["id"] for r in (await adm.get(APPROVALS)).json()] == [theirs["id"]]
    decided = (await prep.get(APPROVALS, params={"decided": "true"})).json()
    assert [(r["id"], r["status"]) for r in decided] == [(mine["id"], "approved")]
    assert (await c.get(APPROVALS, params={"decided": "true"})).json() == []
