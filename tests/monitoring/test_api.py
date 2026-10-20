from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.agent_catalog.runs.models import RunNarrative
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.core.llm.base import LLMError
from tests.agent_catalog.test_runs_api import analyzed_run, assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser

MONITORING = "/api/v1/admin/ai-monitoring"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


@pytest.fixture
async def prep(
    make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory
) -> AsyncClient:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return await signed_in_client(user)


async def test_summary_counts_calls_failures_tokens_and_latency(
    admin: User,
    prep: AsyncClient,
    signed_in_client: ClientFactory,
    db: AsyncSession,
    fake_llm: FakeLLM,
) -> None:
    await analyzed_run(prep)
    await analyzed_run(prep, invoice_number="INV-2")
    fake_llm.error = LLMError("Azure OpenAI timed out")
    failed_run = await analyzed_run(prep, invoice_number="INV-3")
    # An old call outside the 7-day window
    await db.execute(
        update(RunNarrative)
        .where(RunNarrative.run_id == failed_run["id"])
        .values(created_at=utcnow() - timedelta(days=20))
    )
    fake_llm.error = LLMError("rate limited")
    await analyzed_run(prep, invoice_number="INV-4")
    await db.commit()

    c = await signed_in_client(admin)
    body = (await c.get(MONITORING)).json()
    t = body["totals"]
    assert (t["calls"], t["ok"], t["failed"]) == (3, 2, 1)
    assert t["failure_rate"] == pytest.approx(1 / 3)
    assert t["input_tokens"] > 0 and t["p95_latency_ms"] is not None
    assert len(body["daily"]) == 7 and body["daily"][-1]["calls"] == 3
    assert [(a["key"], a["calls"], a["failed"]) for a in body["by_agent"]] == [("ap_invoice", 3, 1)]
    assert body["by_model"][0]["calls"] == 3
    assert [f["error"] for f in body["recent_failures"]] == ["rate limited"]
    assert body["recent_failures"][0]["run"]["agent_key"] == "ap_invoice"
    assert len(body["recent_calls"]) == 3

    month = (await c.get(MONITORING, params={"days": 30})).json()["totals"]
    assert (month["calls"], month["failed"]) == (4, 2)

    summary = (await c.get("/api/v1/overview/summary")).json()
    assert summary["controls"]["model_execution"] == "Guarded · 3 calls, 33% failed (7 days)"


async def test_monitoring_is_admin_only(prep: AsyncClient) -> None:
    assert (await prep.get(MONITORING)).status_code == 403
    assert (await prep.get(MONITORING, params={"days": 0})).status_code in (403, 422)
