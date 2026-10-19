"""Create the demo Finance Admin user from DEMO_ADMIN_* settings.

uv run poe seed                    # create if missing
uv run poe seed --reset-password   # also reset password and unlock
"""

import argparse
import asyncio

from sqlalchemy import select

from src.app.auth.models import User, UserRole
from src.app.auth.security import hash_password
from src.app.core.config import get_settings
from src.app.core.db import get_engine, get_sessionmaker


async def seed_demo_admin(reset_password: bool) -> None:
    settings = get_settings()
    if settings.is_production:
        raise SystemExit("Refusing to seed a demo user in production.")
    if settings.demo_admin_password is None:
        raise SystemExit("Set DEMO_ADMIN_PASSWORD in .env first.")

    email = settings.demo_admin_email.strip().lower()
    password_hash = hash_password(settings.demo_admin_password.get_secret_value())

    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            session.add(
                User(
                    email=email,
                    full_name=settings.demo_admin_name,
                    role=UserRole.FINANCE_ADMIN,
                    password_hash=password_hash,
                )
            )
            print(f"Created {email} (finance_admin)")
        elif reset_password:
            user.password_hash = password_hash
            user.failed_login_attempts = 0
            user.locked_until = None
            print(f"Reset password and unlocked {email}")
        else:
            print(f"{email} already exists - skipped (use --reset-password to reset)")
        await session.commit()
    await get_engine().dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    asyncio.run(seed_demo_admin(args.reset_password))


if __name__ == "__main__":
    main()
