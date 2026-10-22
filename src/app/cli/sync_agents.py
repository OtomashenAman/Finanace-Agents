"""Upsert agent_catalog/registry.py into the agents table.

    uv run poe sync-agents

Runs automatically after migrations (poe db-up, production `migrate` service). Idempotent.
"""

import asyncio

from src.app.agent_catalog.registry import REGISTRY
from src.app.agent_catalog.service import sync_registry
from src.app.core.db import get_engine, get_sessionmaker


async def run() -> None:
    async with get_sessionmaker()() as session:
        result = await sync_registry(session)
        await session.commit()
    await get_engine().dispose()

    print(f"Agents in registry: {len(REGISTRY)}")
    for label, keys in (
        ("created", result.created),
        ("updated", result.updated),
        ("retired", result.retired),
    ):
        if keys:
            print(f"  {label}: {', '.join(keys)}")
    if not (result.created or result.updated or result.retired):
        print("  already in sync")


if __name__ == "__main__":
    asyncio.run(run())
