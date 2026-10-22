"""Background job worker: python -m src.app.cli.worker (run one or more next to the API)."""

import asyncio
import logging
import signal

import src.app.jobs.handlers  # noqa: F401 - registers every handler
from src.app.core.db import get_engine, get_sessionmaker
from src.app.core.llm.factory import get_llm_provider
from src.app.jobs.queue import run_worker


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)  # finish the current job, then exit
    try:
        await run_worker(get_sessionmaker(), get_llm_provider(), stop)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
