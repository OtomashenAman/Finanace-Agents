import io
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.auth.models import User, UserRole
from src.app.cli import admin as cli
from src.app.common.clock import utcnow
from src.app.core.db import get_sessionmaker
from tests.conftest import MakeUser

LOGIN = "/api/v1/auth/login"
PASSWORD = "Server-Typed-Password-9"


async def test_create_makes_a_finance_admin_who_can_sign_in(
    db: AsyncSession, client: AsyncClient
) -> None:
    async with get_sessionmaker()() as session:
        await cli._create(session, "boss@example.com", " The Boss ", PASSWORD)

    user = await db.scalar(select(User).where(User.email == "boss@example.com"))
    assert user is not None
    assert (user.role, user.full_name) == (UserRole.FINANCE_ADMIN, "The Boss")
    assert await db.scalar(select(AuditEvent.id).where(AuditEvent.event_type == "user.created"))
    r = await client.post(LOGIN, json={"email": "boss@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text


async def test_create_refuses_an_existing_email(make_user: MakeUser) -> None:
    await make_user("boss@example.com")
    async with get_sessionmaker()() as session:
        with pytest.raises(SystemExit, match="already exists"):
            await cli._create(session, "boss@example.com", "Boss", PASSWORD)


async def test_reset_unlocks_reactivates_and_sets_the_password(
    make_user: MakeUser, db: AsyncSession, client: AsyncClient
) -> None:
    user = await make_user("boss@example.com", UserRole.FINANCE_ADMIN)
    user.is_active = False
    user.failed_login_attempts = 5
    user.locked_until = utcnow() + timedelta(hours=1)
    await db.commit()

    async with get_sessionmaker()() as session:
        await cli._reset(session, "boss@example.com", PASSWORD)

    r = await client.post(LOGIN, json={"email": "boss@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text


async def test_reset_of_an_unknown_user_says_so() -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(SystemExit, match="No user"):
            await cli._reset(session, "nobody@example.com", PASSWORD)


def test_short_passwords_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    with pytest.raises(SystemExit, match="at least 12"):
        cli._password(from_stdin=True)
