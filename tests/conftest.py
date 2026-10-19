"""Test setup: a separate `<db>_test` database, migrated with Alembic, cleaned per test."""

import asyncio
import os
from collections.abc import AsyncIterator

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

from src.app.core.db import get_sessionmaker  # noqa: E402 - must follow env setup
from src.app.main import app  # noqa: E402

TABLES = ("audit_events", "refresh_tokens", "users")


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
