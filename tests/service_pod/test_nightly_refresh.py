"""The nightly books refresh: every QuickBooks company frozen into the Service POD is synced
and frozen again, like its latest snapshot, so nobody else needs a connection."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.data_sources.exceptions import SyncFailedError
from src.app.data_sources.models import DataSource, FinanceRecord
from src.app.data_sources.records import Customer, RecordType
from src.app.entities.models import LegalEntity
from src.app.jobs.queue import JobContext
from src.app.service_pod.core.snapshots import refresh_job
from src.app.service_pod.core.snapshots.models import PodSnapshot, PodSnapshotSource
from tests.conftest import FakeLLM
from tests.service_pod.test_quickbooks_snapshot import _connection, _invoice

CUSTOMER = Customer(external_id="c1", name="Amy's Bird Sanctuary", email="birds@intuit.example")


async def _freeze(pod: AsyncClient, source: DataSource, entity: LegalEntity) -> dict[str, Any]:
    r = await pod.post(
        "/api/v1/pod/snapshots/quickbooks",
        json={
            "data_source_id": str(source.id),
            "entity_id": str(entity.id),
            "currency": "USD",
            "basis": "Cash",
        },
    )
    assert r.status_code == 201, r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    return snap


def _next_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshots can't be changed, so move the job's clock a day ahead instead."""
    monkeypatch.setattr(refresh_job, "utcnow", lambda: utcnow() + timedelta(days=1))


async def _run(db: AsyncSession, llm: FakeLLM) -> None:
    await refresh_job.refresh_snapshots(db, {"date": "today"}, JobContext(llm, 1, 3))


async def _count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(PodSnapshot)) or 0)


@pytest.fixture
def quickbooks(monkeypatch: pytest.MonkeyPatch, db: AsyncSession) -> dict[uuid.UUID, Any]:
    """Fake QuickBooks: syncing a source adds the invoices queued for it (or raises)."""
    pending: dict[uuid.UUID, Any] = {}

    async def sync(
        session: AsyncSession, user: User, source_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        news = pending.pop(source_id, [])
        if isinstance(news, Exception):
            raise news
        source = await session.get(DataSource, source_id)
        assert source is not None and source.owner_id == user.id
        session.add_all(
            FinanceRecord(
                source_id=source_id,
                record_type=RecordType.INVOICE,
                external_id=i.external_id,
                reference=i.reference,
                counterparty=i.counterparty,
                amount=i.amount,
                txn_date=i.txn_date,
                data=i.model_dump(mode="json"),
            )
            for i in news
        )
        source.last_synced_at = refresh_job.utcnow()  # the (possibly moved) clock
        await session.commit()

    monkeypatch.setattr(refresh_job.data_sources, "sync_source", sync)
    return pending


async def test_books_are_refreshed_like_the_latest_snapshot(
    pod: AsyncClient,
    admin_user: User,
    entity: LegalEntity,
    db: AsyncSession,
    quickbooks: dict[uuid.UUID, Any],
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await _connection(
        db,
        admin_user,
        {
            RecordType.CUSTOMER: [CUSTOMER],
            RecordType.INVOICE: [_invoice("1037", "362.07", "362.07")],
        },
    )
    first = await _freeze(pod, source, entity)
    # Frozen by hand today: tonight leaves it as it is
    await _run(db, fake_llm)
    assert await _count(db) == 1

    # The next night, with a new invoice in QuickBooks: a new snapshot, frozen the same way
    _next_day(monkeypatch)
    quickbooks[source.id] = [_invoice("1040", "50.00", "50.00")]
    await _run(db, fake_llm)
    latest = await db.scalar(select(PodSnapshot).order_by(PodSnapshot.created_at.desc()).limit(1))
    assert latest is not None and str(latest.id) != first["id"]
    assert (latest.entity_id, latest.currency, latest.basis.value) == (entity.id, "USD", "Cash")
    assert latest.imported_by == admin_user.id
    assert latest.row_counts["invoices"] == 2
    assert await db.get(PodSnapshotSource, latest.id) is not None  # still tied to its source

    # Run again the same day (e.g. a retry): nothing new
    before = await _count(db)
    await _run(db, fake_llm)
    assert await _count(db) == before


async def test_only_companies_frozen_before_and_failures_stay_contained(
    pod: AsyncClient,
    admin_user: User,
    entity: LegalEntity,
    db: AsyncSession,
    quickbooks: dict[uuid.UUID, Any],
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    never_frozen = await _connection(db, admin_user, {RecordType.CUSTOMER: [CUSTOMER]})
    broken = await _connection(db, admin_user, {RecordType.CUSTOMER: [CUSTOMER]})
    working = await _connection(
        db,
        admin_user,
        {RecordType.CUSTOMER: [CUSTOMER], RecordType.INVOICE: [_invoice("1", "10.00", "10.00")]},
    )
    await _freeze(pod, broken, entity)
    await _freeze(pod, working, entity)
    _next_day(monkeypatch)
    before = await _count(db)
    ids = (never_frozen.id, broken.id, working.id)  # the job's rollback expires the objects

    quickbooks[ids[0]] = [_invoice("9", "9.00", "9.00")]
    quickbooks[ids[1]] = SyncFailedError("QuickBooks is down")
    quickbooks[ids[2]] = [_invoice("2", "20.00", "20.00")]
    await _run(db, fake_llm)

    # Only the working company got a new snapshot; the never-frozen one was left alone
    assert await _count(db) == before + 1
    assert ids[0] in quickbooks  # its sync was never even called
