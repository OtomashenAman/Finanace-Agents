"""Test setup: a separate `<db>_test` database, migrated with Alembic, cleaned per test."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import Settings, get_settings

# --- point the app at the test database BEFORE anything creates an engine ---------------
_base_url = make_url(Settings().database_url)  # from env or .env
_test_db = _base_url.database or "finance_acc"
if not _test_db.endswith("_test"):
    _test_db = f"{_test_db}_test"
_test_url = _base_url.set(database=_test_db)

os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "false"
get_settings.cache_clear()


async def _ensure_test_database() -> None:
    admin = _base_url.set(drivername="postgresql", database="postgres")
    conn = await asyncpg.connect(admin.render_as_string(hide_password=False))
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _test_db):
            await conn.execute(f'CREATE DATABASE "{_test_db}"')
    finally:
        await conn.close()


asyncio.run(_ensure_test_database())
command.upgrade(Config("alembic.ini"), "head")  # same schema path as production

from src.app.agent_catalog.service import sync_registry  # noqa: E402 - must follow env setup
from src.app.auth.models import User, UserRole  # noqa: E402
from src.app.auth.security import hash_password  # noqa: E402
from src.app.core.db import get_sessionmaker  # noqa: E402
from src.app.main import app  # noqa: E402

TABLES = ("audit_events", "agent_assignments", "agents", "refresh_tokens", "users")
DEFAULT_PASSWORD = "Correct-Horse-Battery-1"


@pytest.fixture(autouse=True)
async def _clean_db() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        await session.commit()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


MakeUser = Callable[..., Awaitable[User]]
ClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
def make_user(db: AsyncSession) -> MakeUser:
    async def _make(email: str, role: UserRole = UserRole.PREPARER) -> User:
        user = User(
            email=email,
            full_name=email.split("@")[0].replace(".", " ").title(),
            role=role,
            password_hash=hash_password(DEFAULT_PASSWORD),
        )
        db.add(user)
        await db.commit()
        return user

    return _make


@pytest.fixture
async def signed_in_client() -> AsyncIterator[ClientFactory]:
    """`await signed_in_client(user)` -> a separate client logged in as that user."""
    clients: list[AsyncClient] = []

    async def _client(user: User) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        r = await c.post(
            "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
        )
        assert r.status_code == 200, r.text
        return c

    yield _client
    for c in clients:
        await c.aclose()


@pytest.fixture
async def synced_agents(db: AsyncSession) -> None:
    """Agents table populated from the code registry."""
    await sync_registry(db)
    await db.commit()
