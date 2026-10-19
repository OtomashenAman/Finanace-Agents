"""Create demo users from DEMO_ADMIN_* settings (development only).

    uv run poe seed                    # create if missing
    uv run poe seed --reset-password   # also reset passwords and unlock

Users (all share DEMO_ADMIN_PASSWORD):
  finance.admin@example.com  Finance Admin (oversight)
  ap.analyst@example.com     preparer for AP Invoice
  ap.approver@example.com    reviewer for AP Invoice
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.service import sync_registry
from src.app.auth.models import User, UserRole
from src.app.auth.security import hash_password
from src.app.core.config import get_settings
from src.app.core.db import get_engine, get_sessionmaker

# email, full name, role, (agent key, capacity) assignments
DEMO_TEAM: list[tuple[str, str, UserRole, list[tuple[str, AgentCapacity]]]] = [
    ("ap.analyst@example.com", "AP Analyst", UserRole.PREPARER,
     [("ap_invoice", AgentCapacity.PREPARER)]),
    ("ap.approver@example.com", "AP Approver", UserRole.REVIEWER,
     [("ap_invoice", AgentCapacity.REVIEWER)]),
]  # fmt: skip


async def _upsert_user(
    session: AsyncSession,
    email: str,
    full_name: str,
    role: UserRole,
    password_hash: str,
    reset_password: bool,
) -> User:
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, full_name=full_name, role=role, password_hash=password_hash)
        session.add(user)
        await session.flush()
        print(f"Created {email} ({role.value})")
    elif reset_password:
        user.password_hash = password_hash
        user.failed_login_attempts = 0
        user.locked_until = None
        print(f"Reset password and unlocked {email}")
    else:
        print(f"{email} already exists - skipped")
    return user


async def _assign(
    session: AsyncSession, user: User, agent_key: str, capacity: AgentCapacity
) -> None:
    agent = await session.scalar(select(Agent).where(Agent.key == agent_key))
    if agent is None:
        return
    exists = await session.scalar(
        select(AgentAssignment.id).where(
            AgentAssignment.user_id == user.id,
            AgentAssignment.agent_id == agent.id,
            AgentAssignment.capacity == capacity,
        )
    )
    if exists is None:
        session.add(AgentAssignment(user_id=user.id, agent_id=agent.id, capacity=capacity))
        print(f"  {user.email}: {capacity.value} on {agent_key}")


async def seed(reset_password: bool) -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Refusing to seed demo users in production.")
    if settings.demo_admin_password is None:
        raise SystemExit("Set DEMO_ADMIN_PASSWORD in .env first.")
    password_hash = hash_password(settings.demo_admin_password.get_secret_value())

    async with get_sessionmaker()() as session:
        await sync_registry(session)  # assignments need the agents table populated
        await _upsert_user(
            session,
            settings.demo_admin_email.strip().lower(),
            settings.demo_admin_name,
            UserRole.FINANCE_ADMIN,
            password_hash,
            reset_password,
        )
        for email, full_name, role, assignments in DEMO_TEAM:
            user = await _upsert_user(
                session, email, full_name, role, password_hash, reset_password
            )
            for agent_key, capacity in assignments:
                await _assign(session, user, agent_key, capacity)
        await session.commit()
    await get_engine().dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    asyncio.run(seed(args.reset_password))


if __name__ == "__main__":
    main()
