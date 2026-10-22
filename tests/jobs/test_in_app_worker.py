import asyncio

import pytest

from src.app import main
from src.app.core.config import get_settings


@pytest.fixture
def worker_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the real worker loop: record each start, then wait for the stop signal."""
    calls: list[str] = []

    async def fake_run_worker(_sessionmaker: object, _llm: object, stop: asyncio.Event) -> None:
        calls.append("start")
        await stop.wait()
        calls.append("stop")

    monkeypatch.setattr(main, "run_worker", fake_run_worker)
    return calls


async def test_worker_runs_inside_the_app_when_enabled(
    monkeypatch: pytest.MonkeyPatch, worker_calls: list[str]
) -> None:
    monkeypatch.setattr(get_settings(), "jobs_worker_in_app", True)
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert worker_calls == ["start"]
    assert worker_calls == ["start", "stop"]  # shutdown waits for the worker


async def test_no_worker_by_default(worker_calls: list[str]) -> None:
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
    assert worker_calls == []


async def test_crashed_worker_is_restarted(monkeypatch: pytest.MonkeyPatch) -> None:
    starts = 0

    async def flaky_run_worker(_sessionmaker: object, _llm: object, stop: asyncio.Event) -> None:
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("database went away")
        await stop.wait()

    monkeypatch.setattr(main, "run_worker", flaky_run_worker)
    monkeypatch.setattr(main, "WORKER_RESTART_SECONDS", 0)
    stop = asyncio.Event()
    task = asyncio.create_task(main.in_app_worker(stop))
    for _ in range(10):
        await asyncio.sleep(0)
    stop.set()
    await task
    assert starts == 2
