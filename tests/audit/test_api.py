import csv
import io
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.audit import service as audit_service
from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext
from tests.agent_catalog.test_runs_api import PDF_EXAMPLE, RUNS, act, analyzed_run, assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

AUDIT = "/api/v1/audit-events"

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


async def events(client: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    r = await client.get(AUDIT, params=params)
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


async def test_admin_sees_everything_users_only_their_own(
    adm: AsyncClient,
    me: AsyncClient,
    make_user: MakeUser,
    db: AsyncSession,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    run = await act(me, await analyzed_run(me), "submit")
    await act(adm, run, "reviews", decision="approved", comment="Checked the receipt")
    other = await make_user("other@example.com")
    await assign(db, other, AgentCapacity.PREPARER)
    c = await signed_in_client(other)
    await analyzed_run(c, invoice_number="OTHER-1")

    everything = {e["summary"] for e in await events(adm)}
    assert f"Approved {run['reference']}" in everything
    assert any(
        s.startswith("Analyzed RUN-") and s != f"Analyzed {run['reference']}" for s in everything
    )

    mine = await events(me)
    summaries = [e["summary"] for e in mine]
    assert f"Approved {run['reference']}" in summaries  # the admin's decision on my run
    assert f"Submitted {run['reference']} for approval" in summaries
    assert all("OTHER" not in str(e["details"]) for e in mine)
    assert {e["actor"]["email"] for e in mine if e["actor"]} == {
        "ap.analyst@example.com",
        "admin@example.com",
    }

    approval = next(e for e in mine if e["event_type"] == "run.approved")
    assert approval["ip"] is None and approval["user_agent"] is None  # the admin's origin
    assert approval["run"]["reference"] == run["reference"]
    assert approval["run"]["agent_key"] == "ap_invoice"
    own_login = next(e for e in mine if e["event_type"] == "auth.login_success")
    assert own_login["ip"] is not None


async def test_user_sees_what_the_admin_did_to_their_account(
    adm: AsyncClient, me: AsyncClient, analyst: User
) -> None:
    r = await adm.post(
        f"/api/v1/users/{analyst.id}/password", json={"password": "A-new-password-1"}
    )
    assert r.status_code == 200
    reset = next(e for e in await events(adm) if e["event_type"] == "user.password_reset")
    assert reset["summary"] == "Set a new password for Ap Analyst"
    assert reset["subject_user"]["email"] == "ap.analyst@example.com"
    # Signed out by the reset: sign in again to look
    me.cookies.clear()
    login = await me.post(
        "/api/v1/auth/login",
        json={"email": "ap.analyst@example.com", "password": "A-new-password-1"},
    )
    assert login.status_code == 200
    assert "Set a new password for Ap Analyst" in {e["summary"] for e in await events(me)}


async def test_filters(adm: AsyncClient, me: AsyncClient, fake_llm: FakeLLM, analyst: User) -> None:
    run = await analyzed_run(me)
    await me.post("/api/v1/auth/login", json={"email": "ap.analyst@example.com", "password": "x"})

    runs_only = await events(adm, category="runs")
    assert runs_only and all(e["category"] == "runs" for e in runs_only)
    assert [e["event_type"] for e in await events(adm, run=run["reference"].lower())] == [
        "run.analyzed",
        "run.created",
    ]
    failures = await events(adm, failures_only="true")
    assert [e["summary"] for e in failures] == ["Sign-in failed (wrong password)"]
    assert all(
        e["actor"]["id"] == str(analyst.id) for e in await events(adm, actor_id=str(analyst.id))
    )
    assert await events(adm, since="2000-01-01", until="2000-01-02") == []


async def test_cursor_pagination(
    adm: AsyncClient, admin: User, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_service, "PAGE_SIZE", 3)
    ctx = RequestContext(ip=None, user_agent=None)
    for n in range(7):
        audit_service.record_event(db, "agent.activated", ctx, actor_id=admin.id, agent_key=f"a{n}")
    await db.commit()

    seen: list[str] = []
    cursor = None
    while True:
        r = (
            await adm.get(
                AUDIT, params={"category": "agents", **({"cursor": cursor} if cursor else {})}
            )
        ).json()
        seen += [e["details"]["agent_key"] for e in r["items"]]
        cursor = r["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == [f"a{n}" for n in range(7)] and len(set(seen)) == 7
    assert (await adm.get(AUDIT, params={"cursor": "garbage"})).status_code == 422


async def test_export_is_admin_only_escaped_and_audited(
    adm: AsyncClient, me: AsyncClient, db: AsyncSession, admin: User
) -> None:
    audit_service.record_event(
        db,
        "data_source.deleted",
        RequestContext(None, None),
        actor_id=admin.id,
        name="=HYPERLINK(1)",
    )
    await db.commit()
    assert (await me.get(f"{AUDIT}/export.csv")).status_code == 403

    r = await adm.get(f"{AUDIT}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    deleted = next(row for row in rows if row["event"] == "data_source.deleted")
    assert deleted["summary"] == "Removed data source =HYPERLINK(1)"  # not at the start: safe
    assert deleted["details"].startswith("{")
    exported = await db.scalar(select(AuditEvent).where(AuditEvent.event_type == "audit.exported"))
    assert exported is not None and exported.details["rows"] == len(rows)


async def test_csv_cells_that_look_like_formulas_are_neutralized() -> None:
    assert audit_service._csv_cell("=SUM(A1)") == "'=SUM(A1)"
    assert audit_service._csv_cell("-1+2") == "'-1+2"
    assert audit_service._csv_cell("Approved RUN-1") == "Approved RUN-1"


async def test_run_timeline(
    adm: AsyncClient,
    me: AsyncClient,
    make_user: MakeUser,
    db: AsyncSession,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    run = await act(me, await analyzed_run(me), "submit")
    await act(adm, run, "reviews", decision="changes_requested", comment="Attach the receipt")
    timeline = (await me.get(f"{RUNS}/{run['id']}/timeline")).json()
    assert [e["event_type"] for e in timeline] == [
        "run.created",
        "run.analyzed",
        "run.submitted",
        "run.changes_requested",
    ]
    assert timeline[-1]["actor"]["email"] == "admin@example.com"
    assert timeline[-1]["ip"] is None

    other = await make_user("other@example.com")
    await assign(db, other, AgentCapacity.PREPARER)
    c = await signed_in_client(other)
    assert (await c.get(f"{RUNS}/{run['id']}/timeline")).status_code == 404
    assert (
        await me.put(f"{RUNS}/{run['id']}/input", json={"values": PDF_EXAMPLE})
    ).status_code == 200
