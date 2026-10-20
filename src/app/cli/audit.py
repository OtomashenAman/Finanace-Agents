"""Audit trail upkeep.

python -m src.app.cli.audit verify          # recompute the hash chain, exit 1 if broken
python -m src.app.cli.audit purge [--days N] # remove events past retention (default:
                                             # AUDIT_RETENTION_DAYS); schedule e.g. daily
"""

import argparse
import asyncio
import sys

from src.app.audit import integrity
from src.app.core.db import get_engine, get_sessionmaker


async def main(args: argparse.Namespace) -> int:
    try:
        async with get_sessionmaker()() as session:
            if args.command == "verify":
                check = await integrity.verify(session)
                if check.valid:
                    print(f"OK: {check.checked} events, chain intact (last hash {check.last_hash})")
                    return 0
                print(f"BROKEN at event #{check.first_broken_seq} ({check.checked} checked)")
                return 1
            result = await integrity.purge(session, args.days)
            print(f"Removed {result.removed} event(s) older than {result.cutoff:%Y-%m-%d}")
            return 0
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    purge = sub.add_parser("purge")
    purge.add_argument("--days", type=int, help="retention in days (default: AUDIT_RETENTION_DAYS)")
    sys.exit(asyncio.run(main(parser.parse_args())))
