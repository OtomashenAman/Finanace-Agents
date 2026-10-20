import itertools
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit import integrity
from src.app.audit.models import AuditEvent
from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from tests.conftest import ClientFactory, MakeUser

CTX = RequestContext(ip="10.0.0.1", user_agent="pytest")


async def add_events(db: AsyncSession, n: int) -> None:
    for i in range(n):
        record_event(db, "agent.activated", CTX, agent_key=f"a{i}")
        await db.commit()


async def test_events_are_chained_and_verify(db: AsyncSession) -> None:
    await add_events(db, 4)
    events = list(await db.scalars(select(AuditEvent).order_by(AuditEvent.seq)))
    assert events[0].prev_hash is None
    for previous, event in itertools.pairwise(events):
        assert event.prev_hash == previous.hash and len(event.hash) == 64
    check = await integrity.verify(db)
    assert (check.checked, check.valid, check.last_hash) == (4, True, events[-1].hash)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET event_type = 'auth.logout'",
        "UPDATE audit_events SET details = '{}'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
async def test_the_trail_is_append_only(db: AsyncSession, statement: str) -> None:
    await add_events(db, 1)
    with pytest.raises(DBAPIError, match="append-only"):
        await db.execute(text(statement))
    await db.rollback()


async def test_deleting_a_user_keeps_their_events(
    make_user: MakeUser, signed_in_client: ClientFactory, db: AsyncSession
) -> None:
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    user = await make_user("leaver@example.com")
    await signed_in_client(user)  # a sign-in event with the user as actor
    assert (await admin.delete(f"/api/v1/users/{user.id}")).status_code == 204
    logins = list(
        await db.scalars(select(AuditEvent).where(AuditEvent.event_type == "auth.login_success"))
    )
    assert len(logins) == 2  # both sign-ins kept...
    assert [e.actor_id for e in logins].count(None) == 1  # ...the leaver's just unlinked
    assert (await integrity.verify(db)).valid is True


async def test_tampering_is_detected(db: AsyncSession, admin_client: AsyncClient) -> None:
    await add_events(db, 3)
    second = (await db.scalars(select(AuditEvent).order_by(AuditEvent.seq))).all()[1]
    # Bypass the guard the way someone with database superuser rights could
    await db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_guard"))
    await db.execute(
        text('UPDATE audit_events SET details = \'{"agent_key": "edited"}\' WHERE seq = :s'),
        {"s": second.seq},
    )
    await db.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_guard"))
    await db.commit()

    check = await integrity.verify(db)
    assert check.valid is False and check.first_broken_seq == second.seq
    body = (await admin_client.get("/api/v1/audit-events/integrity")).json()
    assert body["valid"] is False and body["first_broken_seq"] == second.seq


async def test_retention_purge_removes_old_events_and_is_recorded(db: AsyncSession) -> None:
    await add_events(db, 3)
    await db.execute(text("SET LOCAL finance_acc.audit_purge = 'on'"))
    await db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_guard"))
    await db.execute(
        text(
            "UPDATE audit_events SET created_at = :old WHERE details->>'agent_key' IN ('a0', 'a1')"
        ),
        {"old": utcnow() - timedelta(days=400)},
    )
    await db.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_guard"))
    await db.commit()

    result = await integrity.purge(db, days=365)
    assert result.removed == 2 and result.anchor_hash is not None
    remaining = [
        e.event_type for e in await db.scalars(select(AuditEvent).order_by(AuditEvent.seq))
    ]
    assert remaining == ["agent.activated", "audit.purged"]
    # The tampered created_at made those two hashes stale, but they're gone: the rest verifies
    assert (await integrity.verify(db)).valid is True


@pytest.fixture
async def admin_client(make_user: MakeUser, signed_in_client: ClientFactory) -> AsyncClient:
    admin: User = await make_user("admin@example.com", UserRole.FINANCE_ADMIN)
    return await signed_in_client(admin)
