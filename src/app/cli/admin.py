"""Finance Admin accounts from the server (works in production, unlike the demo seed).

    python -m src.app.cli.admin list
    python -m src.app.cli.admin create aman.a@e-solutionsinc.com "Aman Aditya"
    python -m src.app.cli.admin reset-password aman.a@e-solutionsinc.com

The password is asked for (twice) and never stored in a file; --password-stdin reads it from
standard input instead (scripts). reset-password also unlocks and reactivates the account and
signs it out everywhere. Everything else (users, roles, agents) is done in the app by an admin.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.auth.security import hash_password
from src.app.auth.service import resolve_reset_requests, revoke_user_tokens
from src.app.common.context import RequestContext
from src.app.core.db import get_engine, get_sessionmaker
from src.app.users.schemas import PASSWORD_MIN_LENGTH

CTX = RequestContext(ip=None, user_agent="admin cli")


def _password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("New password: ")
        if getpass.getpass("Again: ") != password:
            raise SystemExit("The passwords don't match.")
    if not PASSWORD_MIN_LENGTH <= len(password) <= 256:
        raise SystemExit(f"The password must have at least {PASSWORD_MIN_LENGTH} characters.")
    return password


async def _list(session: AsyncSession) -> None:
    users = await session.scalars(select(User).order_by(User.role, User.email))
    for user in users:
        state = "active" if user.is_active else "deactivated"
        if user.locked_until is not None:
            state += ", locked"
        print(f"{user.role.value:14} {user.email:40} {state}")


async def _create(session: AsyncSession, email: str, name: str, password: str) -> None:
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise SystemExit(f"{email} already exists: use reset-password.")
    user = User(
        email=email,
        full_name=name.strip(),
        role=UserRole.FINANCE_ADMIN,
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.flush()
    record_event(
        session, "user.created", CTX, user_id=str(user.id), email=email, role=user.role.value
    )
    await session.commit()
    print(f"Created Finance Admin {email}")


async def _reset(session: AsyncSession, email: str, password: str) -> None:
    user = await session.scalar(select(User).where(User.email == email).with_for_update())
    if user is None:
        raise SystemExit(f"No user {email}: use create.")
    user.password_hash = hash_password(password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.is_active = True
    await revoke_user_tokens(session, user.id)
    await resolve_reset_requests(session, user.id)
    record_event(session, "user.password_reset", CTX, user_id=str(user.id))
    await session.commit()
    print(f"New password set for {email} (unlocked, active, signed out everywhere)")


async def run(args: argparse.Namespace) -> None:
    password = _password(args.password_stdin) if args.command != "list" else ""
    async with get_sessionmaker()() as session:
        if args.command == "list":
            await _list(session)
        elif args.command == "create":
            await _create(session, args.email.strip().lower(), args.name, password)
        else:
            await _reset(session, args.email.strip().lower(), password)
    await get_engine().dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="every user, role and state")
    create = commands.add_parser("create", help="a new Finance Admin")
    create.add_argument("email")
    create.add_argument("name")
    reset = commands.add_parser("reset-password", help="new password, unlock, reactivate")
    reset.add_argument("email")
    for sub in (create, reset):
        sub.add_argument("--password-stdin", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
