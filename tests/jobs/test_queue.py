from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.agent_catalog.runs.jobs import NARRATIVE_JOB
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.core.config import get_settings
from src.app.core.db import get_sessionmaker
from src.app.core.llm.base import LLMError
from src.app.jobs import queue
from src.app.jobs.models import Job, JobStatus
from tests.agent_catalog.test_runs_api import PDF_EXAMPLE, RUNS, act, assign, new_run
from tests.conftest import ClientFactory, FakeLLM, MakeUser

JOBS = "/api/v1/admin/jobs"

pytestmark = pytest.mark.usefixtures("synced_agents")


@pytest.fixture(autouse=True)
def queue_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_mode", "queue")


@pytest.fixture
async def me(make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory) -> AsyncClient:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return await signed_in_client(user)


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


async def work(llm: FakeLLM) -> bool:
    async with get_sessionmaker()() as session:
        return await queue.work_once(session, "test-worker", llm)


async def due_now(db: AsyncSession) -> None:
    await db.execute(update(Job).values(run_after=utcnow() - timedelta(seconds=1)))
    await db.commit()


async def test_analysis_returns_at_once_and_the_worker_drafts_the_explanation(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await act(me, await new_run(me, PDF_EXAMPLE), "analyze")
    assert run["status"] == "analyzed"  # deterministic result is there immediately
    assert run["narrative"] is None and run["narrative_pending"] is True
    assert run["permissions"]["can_submit"] is False
    r = await me.post(f"{RUNS}/{run['id']}/submit")
    assert r.status_code == 409 and "still being drafted" in r.json()["detail"]["message"]
    assert fake_llm.calls == []

    assert await work(fake_llm) is True
    assert await work(fake_llm) is False  # nothing left
    run = (await me.get(f"{RUNS}/{run['id']}")).json()
    assert run["narrative"]["status"] == "ok" and run["narrative_pending"] is False
    assert run["permissions"]["can_submit"] is True


async def test_enqueue_is_idempotent(db: AsyncSession) -> None:
    first = await queue.enqueue(db, NARRATIVE_JOB, {"run_id": "x"}, dedupe_key="same")
    again = await queue.enqueue(db, NARRATIVE_JOB, {"run_id": "x"}, dedupe_key="same")
    await db.commit()
    assert first is not None and again is None
    assert len(list(await db.scalars(select(Job)))) == 1
    with pytest.raises(ValueError, match="No handler"):
        await queue.enqueue(db, "nope", {})


async def test_failures_retry_with_backoff_then_wait_for_an_admin(
    me: AsyncClient,
    admin: User,
    signed_in_client: ClientFactory,
    db: AsyncSession,
    fake_llm: FakeLLM,
) -> None:
    run = await act(me, await new_run(me, PDF_EXAMPLE), "analyze")
    fake_llm.error = LLMError("Azure OpenAI timed out")

    assert await work(fake_llm) is True
    job = await db.scalar(select(Job))
    assert job is not None
    await db.refresh(job)
    assert (job.status, job.attempts) == (JobStatus.QUEUED, 1)
    assert job.run_after > utcnow() + timedelta(seconds=5)  # backed off
    assert "timed out" in (job.last_error or "")
    assert await work(fake_llm) is False  # not due yet

    for _ in range(2):
        await due_now(db)
        await work(fake_llm)
    await db.refresh(job)
    assert (job.status, job.attempts) == (JobStatus.FAILED, 3)
    seen = (await me.get(f"{RUNS}/{run['id']}")).json()
    assert seen["narrative"]["status"] == "failed" and seen["narrative_pending"] is False

    adm = await signed_in_client(admin)
    body = (await adm.get(JOBS)).json()
    assert body["failed"] == 1
    [failure] = body["failures"]
    assert failure["run_reference"] == run["reference"]
    assert failure["run_link"] == f"/catalog/ap_invoice/runs/{run['id']}"
    assert (await me.get(JOBS)).status_code == 403

    fake_llm.error = None
    retried = (await adm.post(f"{JOBS}/{failure['id']}/retry")).json()
    assert retried["status"] == "queued"
    assert (await adm.post(f"{JOBS}/{failure['id']}/retry")).status_code == 409
    assert await work(fake_llm) is True
    assert (await me.get(f"{RUNS}/{run['id']}")).json()["narrative"]["status"] == "ok"


async def test_a_newer_analysis_supersedes_the_queued_one(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await act(me, await new_run(me, PDF_EXAMPLE), "analyze")
    await act(me, run, "analyze")  # again: a second job for the new analysis
    while await work(fake_llm):
        pass
    assert len(fake_llm.calls) == 1  # the stale job did nothing


async def test_stale_running_jobs_are_requeued(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = await queue.enqueue(db, NARRATIVE_JOB, {"run_id": "gone"}, dedupe_key="k")
    assert job is not None
    job.status = JobStatus.RUNNING
    job.locked_at = utcnow() - timedelta(hours=1)
    await db.commit()
    assert await queue.recover_stale(db) == 1
    await db.refresh(job)
    assert job.status == JobStatus.QUEUED


async def test_create_run_is_idempotent(me: AsyncClient) -> None:
    headers = {"Idempotency-Key": "click-123"}
    first = await me.post(RUNS, headers=headers)
    again = await me.post(RUNS, headers=headers)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    other = await me.post(RUNS, headers={"Idempotency-Key": "click-456"})
    assert other.json()["id"] != first.json()["id"]
