import json
import logging
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from src.app.core import observability
from src.app.core.config import get_settings
from src.app.core.observability import HttpCounters, JsonFormatter, request_id


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    generated = await client.get("/health")
    assert len(generated.headers["x-request-id"]) == 32
    echoed = await client.get("/health", headers={"X-Request-ID": "trace-abc.1"})
    assert echoed.headers["x-request-id"] == "trace-abc.1"
    unsafe = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert unsafe.headers["x-request-id"] != "bad id\nwith newline"


async def test_ready_checks_the_database(client: AsyncClient) -> None:
    r = await client.get("/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready", "database": "ok"}


async def test_metrics_cover_http_and_business_health(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.get("/api/v1/auth/me")
    body = (await client.get("/metrics")).text
    assert (
        'finance_acc_http_requests_total{method="GET",route="/api/v1/auth/me",status="401"}' in body
    )
    assert "finance_acc_http_request_duration_seconds_bucket" in body
    for gauge in (
        'finance_acc_jobs{status="failed"} 0',
        "finance_acc_jobs_oldest_queued_seconds 0",
        'finance_acc_llm_calls_24h{status="failed"} 0',
        "finance_acc_runs_overdue_approval 0",
        "finance_acc_locked_accounts 0",
        'finance_acc_data_sources{status="needs_reauth"} 0',
    ):
        assert gauge in body

    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("s3cret"))
    assert (await client.get("/metrics")).status_code == 401
    ok = await client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_json_logs_include_the_request_id() -> None:
    token = request_id.set("req-42")
    try:
        record = logging.LogRecord(
            "finance_acc.access", logging.INFO, "", 0, "GET / 200", None, None
        )
        record.request_id = request_id.get()
        record.fields = {"status": 200}
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id.reset(token)
    assert line["request_id"] == "req-42"
    assert line["status"] == 200 and line["level"] == "info" and line["msg"] == "GET / 200"


def test_metrics_from_several_processes_are_summed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = HttpCounters()  # another server process
    other.observe("GET", "/api/v1/runs", 200, 0.07)
    other.observe("GET", "/api/v1/runs", 200, 3.0)
    (tmp_path / "http-99-abc.json").write_text(json.dumps(other.to_json()))
    (tmp_path / "http-98-old.json").write_text("{half a file")  # skipped, not fatal

    mine = HttpCounters()
    mine.observe("GET", "/api/v1/runs", 200, 0.02)
    monkeypatch.setattr(observability, "_counters", mine)
    observability.configure_metrics(str(tmp_path))
    try:
        body = "\n".join(observability.http_metrics())
    finally:
        observability.configure_metrics(None)

    route = 'method="GET",route="/api/v1/runs"'
    assert f'finance_acc_http_requests_total{{{route},status="200"}} 3' in body
    assert f'finance_acc_http_request_duration_seconds_bucket{{{route},le="0.1"}} 2' in body
    assert f"finance_acc_http_request_duration_seconds_count{{{route}}} 3" in body
    assert (tmp_path / observability._metrics_file).exists()  # this process's own file
