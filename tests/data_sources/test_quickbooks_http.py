"""QuickBooks HTTP behaviour: backoff on throttling and server errors, never resending writes."""

import httpx
import pytest

from src.app.data_sources.models import IntegrationEnvironment
from src.app.data_sources.providers import quickbooks as qb

APP = qb.AppCredentials("id", "secret", IntegrationEnvironment.SANDBOX)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qb, "RETRY_DELAYS", (0.0, 0.0))


def api(*statuses: int) -> tuple[qb.Api, list[httpx.Request]]:
    """An Api whose calls get these statuses in turn (then 200)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = statuses[len(seen) - 1] if len(seen) <= len(statuses) else 200
        return httpx.Response(status, json={"Bill": {"Id": "1"}, "QueryResponse": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return qb.Api(client, APP, "123", "token"), seen


async def test_throttled_reads_are_retried_then_succeed() -> None:
    qbo, seen = api(429, 503)
    assert await qbo.get_bill("1") == {"Id": "1"}
    assert len(seen) == 3


async def test_reads_give_up_after_the_last_retry() -> None:
    qbo, seen = api(500, 500, 500)
    with pytest.raises(qb.QuickBooksError, match=r"\(500\)"):
        await qbo.get_bill("1")
    assert len(seen) == 3


async def test_a_failed_write_is_never_resent() -> None:
    qbo, seen = api(500)
    with pytest.raises(qb.QuickBooksError):
        await qbo.set_bill_note({"Id": "1", "SyncToken": "0", "VendorRef": {"value": "5"}}, "x")
    assert len(seen) == 1  # it may have been applied: never risk a second update


async def test_a_throttled_write_was_not_applied_and_is_resent() -> None:
    qbo, seen = api(429)
    await qbo.set_bill_note({"Id": "1", "SyncToken": "0", "VendorRef": {"value": "5"}}, "x")
    assert len(seen) == 2


async def test_reports_are_read_on_an_explicit_accounting_method() -> None:
    qbo, seen = api()
    await qbo.report("TrialBalance", start_date="2026-09-01", accounting_method="Accrual")
    assert seen[0].url.params["accounting_method"] == "Accrual"
