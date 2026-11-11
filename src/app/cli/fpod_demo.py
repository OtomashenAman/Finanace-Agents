"""Load the Finance POD demo data from the command line (the same as Setup > Demo data).

    python -m src.app.cli.fpod_demo admin@example.com

The email is the Finance Admin who loads it (the requester and buyer in the demo). Safe to
run again: what is already there is left alone. No email is sent.
"""

import argparse
import asyncio

from sqlalchemy import select

from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext
from src.app.core.db import get_engine, get_sessionmaker
from src.app.finance_pod import demo


async def run(email: str) -> None:
    async with get_sessionmaker()() as session:
        me = await session.scalar(select(User).where(User.email == email.strip().lower()))
        if me is None or me.role != UserRole.FINANCE_ADMIN:
            raise SystemExit(f"{email} isn't a Finance Admin.")
        result = await demo.load(session, me, RequestContext(ip=None, user_agent="fpod_demo cli"))
    await get_engine().dispose()
    for line in result.loaded:
        print(f"loaded   {line}")
    for line in result.skipped:
        print(f"skipped  {line} (already there)")
    for line in result.notes:
        print(f"note     {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    asyncio.run(run(parser.parse_args().email))


if __name__ == "__main__":
    main()
