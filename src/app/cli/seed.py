"""Create demo users from DEMO_ADMIN_* settings (development only).

    uv run poe seed                    # create if missing
    uv run poe seed --reset-password   # also reset passwords and unlock
    uv run poe seed --finance-team     # also the Finance POD team (one user per capacity)
    uv run poe seed --erpnext          # also connect the local ERPNext and take a snapshot

`docker compose up` runs it (migrate: --finance-team; erpnext-seed: --erpnext once ERPNext
is seeded), so a fresh machine starts with every user and the ERPNext demo company.

Users (both share DEMO_ADMIN_PASSWORD):
  finance.admin@example.com  Finance Admin (every agent, user management)
  demo.user@example.com      user: prepares runs on the agents with a workspace (the admin
                             approves them)

Also a demo legal entity (US01 · US Operations) the demo user works for, unless entities
already exist.

The Finance POD team (--finance-team, same password): one user per capacity, e.g.
bo.gia@example.com the budget owner (FINANCE_TEAM). A Finance Admin can also open a tab as
any of them with no password ("Testing? Do it as ..." on a case).
"""

import argparse
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.agent_catalog.registry import AGENTS
from src.app.agent_catalog.service import sync_registry
from src.app.auth.models import User, UserRole
from src.app.auth.security import hash_password
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.core.db import get_engine, get_sessionmaker
from src.app.data_sources import service as data_sources
from src.app.data_sources.models import DataSource, IntegrationEnvironment, SourceKind
from src.app.data_sources.schemas import ErpNextConnect
from src.app.entities.models import EntityAssignment, LegalEntity
from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.models import FinanceCapacityAssignment
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.schemas import ErpNextSnapshotRequest

# email, full name, role, (agent key, capacity) assignments
DEMO_TEAM: list[tuple[str, str, UserRole, list[tuple[str, AgentCapacity]]]] = [
    ("demo.user@example.com", "Demo User", UserRole.USER,
     [(a.key, AgentCapacity.PREPARER) for a in AGENTS if a.has_workspace()]),
]  # fmt: skip


# The Finance POD's test team: one person per capacity the workflows use (every entity)
FINANCE_TEAM: list[tuple[str, str, list[Cap]]] = [
    ("req.gia@example.com", "Riya Requester", [Cap.REQUESTER]),
    ("bo.gia@example.com", "Bharat BudgetOwner", [Cap.BUDGET_OWNER]),
    ("buyer.gia@example.com", "Bina Buyer", [Cap.BUYER]),
    ("receiver.gia@example.com", "Ravi Receiver", [Cap.RECEIVER]),
    ("analyst.gia@example.com", "Arun APAnalyst", [Cap.AP_ANALYST]),
    ("approver.gia@example.com", "Vani VendorApprover", [Cap.VENDOR_APPROVER]),
    ("controller.gia@example.com", "Chitra Controller", [Cap.CONTROLLER]),
    ("credit.gia@example.com", "Kiran CreditController", [Cap.CREDIT_CONTROLLER]),
    ("billing.gia@example.com", "Meera BillingAnalyst", [Cap.BILLING_ANALYST]),
]
SEED_CTX = RequestContext(ip=None, user_agent="seed")


async def _grant(session: AsyncSession, user: User, capacity: Cap) -> None:
    held = await session.scalar(
        select(FinanceCapacityAssignment.id).where(
            FinanceCapacityAssignment.user_id == user.id,
            FinanceCapacityAssignment.capacity == capacity,
        )
    )
    if held is None:
        session.add(FinanceCapacityAssignment(user_id=user.id, capacity=capacity))
        print(f"  {user.email}: {capacity.value}")


async def _connect_erpnext(session: AsyncSession, admin: User, entity: LegalEntity) -> None:
    """The local ERPNext (ERPNEXT_URL / _API_KEY / _API_SECRET / _COMPANY) as the admin's
    data source, and a first snapshot of it. An existing ERPNext connection is left alone."""
    if await session.scalar(select(DataSource.id).where(DataSource.kind == SourceKind.ERPNEXT)):
        print("An ERPNext connection already exists - skipped")
        return
    key, secret = os.environ.get("ERPNEXT_API_KEY"), os.environ.get("ERPNEXT_API_SECRET")
    if not (key and secret):
        raise SystemExit("Set ERPNEXT_API_KEY and ERPNEXT_API_SECRET to connect ERPNext.")
    body = ErpNextConnect(
        name="GIA Demo Labs (local ERPNext)",
        base_url=os.environ.get("ERPNEXT_URL", "http://host.docker.internal:8090"),
        api_key=key,
        api_secret=secret,
        company=os.environ.get("ERPNEXT_COMPANY", "GIA Demo Labs"),
        environment=IntegrationEnvironment.SANDBOX,
    )
    source = await data_sources.connect_erpnext(session, admin, body, SEED_CTX)
    print(f"Connected ERPNext {body.base_url} ({body.company})")
    access = PodAccess(user=admin)
    request = ErpNextSnapshotRequest(data_source_id=source.id, entity_id=entity.id)
    result = await snapshots.import_erpnext(session, access, request, SEED_CTX)
    print(f"Took a first snapshot of it ({result.snapshot.id})")


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


async def _demo_entity(session: AsyncSession) -> LegalEntity | None:
    """A first entity for a fresh database; existing setups are left alone."""
    if await session.scalar(select(LegalEntity.id).limit(1)) is not None:
        return await session.scalar(select(LegalEntity).where(LegalEntity.code == "US01"))
    entity = LegalEntity(code="US01", name="US Operations")
    session.add(entity)
    await session.flush()
    print("Created legal entity US01 · US Operations")
    return entity


async def _assign_entity(session: AsyncSession, user: User, entity: LegalEntity) -> None:
    exists = await session.scalar(
        select(EntityAssignment.id).where(
            EntityAssignment.user_id == user.id, EntityAssignment.entity_id == entity.id
        )
    )
    if exists is None:
        session.add(EntityAssignment(user_id=user.id, entity_id=entity.id))
        print(f"  {user.email}: works for {entity.code}")


async def seed(
    reset_password: bool, finance_team: bool = False, erpnext: bool = False,
    demo_user: bool = True,
) -> None:  # fmt: skip
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Refusing to seed demo users in production.")
    if settings.demo_admin_password is None:
        raise SystemExit("Set DEMO_ADMIN_PASSWORD in .env first.")
    password_hash = hash_password(settings.demo_admin_password.get_secret_value())

    async with get_sessionmaker()() as session:
        await sync_registry(session)  # assignments need the agents table populated
        admin = await _upsert_user(
            session,
            settings.demo_admin_email.strip().lower(),
            settings.demo_admin_name,
            UserRole.FINANCE_ADMIN,
            password_hash,
            reset_password,
        )
        entity = await _demo_entity(session)
        for email, full_name, role, assignments in DEMO_TEAM if demo_user else []:
            user = await _upsert_user(
                session, email, full_name, role, password_hash, reset_password
            )
            for agent_key, capacity in assignments:
                await _assign(session, user, agent_key, capacity)
            if entity is not None:
                await _assign_entity(session, user, entity)
        if finance_team:
            for email, full_name, capacities in FINANCE_TEAM:
                member = await _upsert_user(
                    session, email, full_name, UserRole.USER, password_hash, reset_password
                )
                for held in capacities:
                    await _grant(session, member, held)
        await session.commit()
        if erpnext:
            if entity is None:
                entity = await session.scalar(select(LegalEntity).limit(1))
            if entity is None:
                raise SystemExit("No legal entity to take the ERPNext snapshot for.")
            await _connect_erpnext(session, admin, entity)
    await get_engine().dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-password", action="store_true")
    parser.add_argument(
        "--finance-team",
        action="store_true",
        help="also the Finance POD team, one user per capacity",
    )
    parser.add_argument(
        "--erpnext",
        action="store_true",
        help="also connect the local ERPNext and take a first snapshot",
    )
    parser.add_argument(
        "--no-demo-user",
        action="store_true",
        help="skip demo.user@example.com (the agents' preparer)",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.reset_password, args.finance_team, args.erpnext, not args.no_demo_user))


if __name__ == "__main__":
    main()
