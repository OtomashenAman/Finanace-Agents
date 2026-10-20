from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.agent_catalog.runs.models import AgentRun
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.data_sources.models import DataSource, SourceKind, SourceStatus
from tests.agent_catalog.test_runs_api import PDF_EXAMPLE, RUNS, act, analyzed_run, assign, new_run
from tests.conftest import ClientFactory, FakeLLM, MakeUser

WORKLIST = "/api/v1/worklist"

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


async def worklist(client: AsyncClient) -> dict[str, Any]:
    r = await client.get(WORKLIST)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def kinds(items: list[dict[str, Any]]) -> list[str]:
    return [i["kind"] for i in items]


async def test_user_sees_their_own_next_steps_in_order(
    adm: AsyncClient, me: AsyncClient, db: AsyncSession, fake_llm: FakeLLM
) -> None:
    draft = await new_run(me)
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == draft["id"])
        .values(updated_at=utcnow() - timedelta(days=9))
    )
    await db.commit()
    failed = await act(me, await new_run(me, {"supplier": "Acme"}), "analyze")
    assert failed["status"] == "validation_failed"
    ready = await analyzed_run(me, invoice_number="READY-1")
    back = await act(me, await analyzed_run(me, invoice_number="BACK-1"), "submit")
    await act(adm, back, "reviews", decision="changes_requested", comment="Attach the receipt")
    waiting = await act(me, await analyzed_run(me, invoice_number="WAIT-1"), "submit")

    body = await worklist(me)
    assert kinds(body["action"]) == [
        "changes_requested",
        "validation_failed",
        "ready_to_submit",
        "draft",
    ]
    by_kind = {i["kind"]: i for i in body["action"]}
    assert by_kind["changes_requested"]["detail"] == "Attach the receipt"
    assert by_kind["changes_requested"]["action_label"] == "Fix & resubmit"
    assert by_kind["ready_to_submit"]["title"] == f"{ready['reference']} · READY-1"
    assert by_kind["draft"]["overdue"] is True  # stale
    assert by_kind["draft"]["link"] == f"/catalog/ap_invoice/runs/{draft['id']}"
    assert [i["title"] for i in body["waiting"]] == [f"{waiting['reference']} · WAIT-1"]
    assert body["info"] == []


async def test_admin_sees_approvals_with_the_sla_and_only_what_they_can_approve(
    adm: AsyncClient,
    me: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    db: AsyncSession,
    fake_llm: FakeLLM,
) -> None:
    old = await act(me, await analyzed_run(me, invoice_number="OLD-1"), "submit")
    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == old["id"])
        .values(submitted_at=utcnow() - timedelta(hours=30))
    )
    await db.commit()
    fresh = await act(me, await analyzed_run(me, invoice_number="NEW-1"), "submit")

    body = await worklist(adm)
    approvals = [i for i in body["action"] if i["kind"] == "approve"]
    assert [i["title"].split(" · ")[1] for i in approvals] == ["OLD-1", "NEW-1"]  # overdue first
    assert approvals[0]["overdue"] is True and approvals[1]["overdue"] is False
    assert approvals[0]["context"] == "AP Invoice · Ap Analyst"

    # Two approvals needed: once this admin approved, it's someone else's turn
    await make_user("second.admin@example.com", UserRole.FINANCE_ADMIN)
    await adm.put(
        "/api/v1/admin/governance/approval-matrix/ap_invoice",
        json={"tiers": [{"min_amount": "0", "approvals_required": 2}]},
    )
    two = await act(me, await analyzed_run(me, invoice_number="TWO-1"), "submit")
    await act(adm, two, "reviews", decision="approved", comment="First approval")
    titles = [i["title"] for i in (await worklist(adm))["action"] if i["kind"] == "approve"]
    assert all("TWO-1" not in t for t in titles)
    assert fresh["reference"] in " ".join(titles)

    # Users never get approvals in their list
    assert "approve" not in kinds((await worklist(me))["action"])


async def test_admin_sees_locked_accounts_and_users_connection_problems(
    adm: AsyncClient, me: AsyncClient, analyst: User, db: AsyncSession
) -> None:
    db.add(
        DataSource(
            owner_id=analyst.id,
            kind=SourceKind.QUICKBOOKS,
            name="Acme Books",
            status=SourceStatus.NEEDS_REAUTH,
            last_error="QuickBooks access expired or was revoked.",
            record_counts={},
        )
    )
    await db.execute(
        update(User)
        .where(User.id == analyst.id)
        .values(locked_until=utcnow() + timedelta(minutes=10))
    )
    await db.commit()

    body = await worklist(adm)
    locked = [i for i in body["action"] if i["kind"] == "locked_account"]
    assert [(i["title"], i["action_label"]) for i in locked] == [("Ap Analyst", "Unlock")]
    [problem] = body["info"]
    assert problem["kind"] == "user_data_source" and problem["action_label"] is None
    assert "Only Ap Analyst can fix it" in problem["detail"]

    await db.execute(update(User).where(User.id == analyst.id).values(locked_until=None))
    await db.commit()
    mine = await worklist(me)
    [source] = [i for i in mine["action"] if i["kind"] == "data_source"]
    assert (source["title"], source["action_label"]) == ("Acme Books", "Re-authorize")
    assert mine["info"] == []


async def test_worklist_follows_run_isolation(
    me: AsyncClient,
    make_user: MakeUser,
    db: AsyncSession,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    await new_run(me, PDF_EXAMPLE)
    other = await make_user("other@example.com")
    await assign(db, other, AgentCapacity.PREPARER)
    assert (await worklist(await signed_in_client(other)))["action"] == []
    assert len((await me.get(RUNS)).json()) == 1
