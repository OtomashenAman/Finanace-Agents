"""Financial Close prefilled from month-end history: trial balance and AR/AP aging totals."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole
from src.app.data_sources.providers.quickbooks import (
    _aging_total,
    _trial_balance,
    history_periods,
)
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import REPORTS, FakeIntuit, connect, intuit  # noqa: F401

pytestmark = pytest.mark.usefixtures("synced_agents")

AGENT = "/api/v1/agents/financial_close"
RUNS = f"{AGENT}/runs"


# --- report parsing ---------------------------------------------------------------------------


def test_trial_balance_rows_become_debit_positive_balances() -> None:
    accounts = {"84": {"AccountType": "Accounts Receivable", "AcctNum": "1200"}}
    balances = _trial_balance(REPORTS["TrialBalance"], "2026-09", accounts)

    assert [(b.account_name, b.balance) for b in balances] == [
        ("Operating Account", Decimal("250000.00")),  # "250,000.00": commas are fine
        ("Accounts Receivable (A/R)", Decimal("120000.00")),
        ("Accounts Payable (A/P)", Decimal("-49000.00")),  # a credit
    ]
    receivables = balances[1]
    assert receivables.account_type == "Accounts Receivable"
    assert receivables.account_number == "1200"
    assert receivables.external_id == "84-2026-09"
    assert receivables.matches("1200") and receivables.matches("accounts receivable (a/r)")


def test_aging_total_from_grand_total_or_rows() -> None:
    assert _aging_total(REPORTS["AgedReceivables"]) == Decimal("119000.00")
    assert _aging_total(REPORTS["AgedPayables"]) == Decimal("49000.00")  # no total row
    assert _aging_total({}) == Decimal(0)


def test_history_covers_the_last_24_complete_months() -> None:
    periods = history_periods(date(2026, 1, 15))
    assert (periods[0], periods[-1], len(periods)) == ("2025-12", "2024-01", 24)


# --- prefill ----------------------------------------------------------------------------------


@pytest.fixture
async def me(
    make_user: MakeUser,
    db: AsyncSession,
    signed_in_client: ClientFactory,
    intuit: FakeIntuit,  # noqa: F811 - the fixture imported above
) -> AsyncClient:
    user = await make_user("controller@example.com", UserRole.USER)
    await assign(db, user, AgentCapacity.PREPARER, key="financial_close")
    return await signed_in_client(user)


@pytest.fixture
async def source_id(me: AsyncClient) -> str:
    """The user's QuickBooks, connected and synced (month-end history included)."""
    result: str = (await connect(me))["source"][0]
    return result


async def prefilled(client: AsyncClient, source_id: str, account: str, period: str) -> Any:
    run = (await client.post(RUNS)).json()
    r = await client.post(
        f"{RUNS}/{run['id']}/prefill",
        json={"source_id": source_id, "params": {"gl_account": account, "close_period": period}},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_options_come_from_the_month_end_balances(me: AsyncClient, source_id: str) -> None:
    options = (await me.get(f"{AGENT}/prefill-options", params={"source_id": source_id})).json()

    assert options["gl_account"] == [
        "Accounts Payable (A/P)",
        "Accounts Receivable (A/R)",
        "Operating Account",
    ]
    assert len(options["close_period"]) == 24
    assert options["close_period"] == sorted(options["close_period"], reverse=True)

    form = (await me.get(f"{AGENT}/form")).json()
    assert [(f["name"], f["kind"]) for f in form["prefill_fields"]] == [
        ("gl_account", "choice"),
        ("close_period", "choice"),
    ]


async def test_receivables_control_account_against_the_ar_aging(
    me: AsyncClient, source_id: str, fake_llm: FakeLLM
) -> None:
    periods = (await me.get(f"{AGENT}/prefill-options", params={"source_id": source_id})).json()[
        "close_period"
    ]
    latest = periods[0]
    run = await prefilled(me, source_id, "Accounts Receivable (A/R)", latest)

    assert run["input"]["gl_account"] == "Accounts Receivable (A/R)"
    assert run["input"]["close_period"] == latest
    assert run["input"]["gl_balance"] == "120000.00"
    assert run["input"]["subledger_balance"] == "119000.00"  # the AR aging total
    records = run["source"]["records"]
    assert records["account_balance"]["account_type"] == "Accounts Receivable"
    assert records["subledger_total"]["ledger"] == "AR"
    assert records["summary"]["books_closed_through"] == "2026-08-31"
    assert run["source"]["record_reference"] == f"Accounts Receivable (A/R) · {latest}"

    fake_llm.output["cited_fields"] = ["gl_balance"]
    values = {**run["input"], "materiality_threshold": "500"}
    await me.put(f"{RUNS}/{run['id']}/input", json={"values": values})
    run = (await me.post(f"{RUNS}/{run['id']}/analyze")).json()
    flags = {f["code"]: f["severity"] for f in run["flags"]}
    assert flags["MATERIAL_VARIANCE"] == "high"  # 1,000 > 500
    # The latest month ends after the books closing date (31 Aug 2026)
    assert flags["PERIOD_NOT_CLOSED"] == "warning"

    oldest = await prefilled(me, source_id, "1200", periods[-1])  # by account number
    oldest_values = {**oldest["input"], "materiality_threshold": "500"}
    await me.put(f"{RUNS}/{oldest['id']}/input", json={"values": oldest_values})
    oldest = (await me.post(f"{RUNS}/{oldest['id']}/analyze")).json()
    assert {f["code"]: f["severity"] for f in oldest["flags"]}["PERIOD_CLOSED"] == "pass"


async def test_payables_are_shown_credit_positive(me: AsyncClient, source_id: str) -> None:
    run = await prefilled(me, source_id, "Accounts Payable (A/P)", "2026-08")

    # Trial balance -49,000.00 (a credit) vs AP aging 49,000.00: compared on the same sign
    assert run["input"]["gl_balance"] == "49000.00"
    assert run["input"]["subledger_balance"] == "49000.00"
    summary = run["source"]["records"]["summary"]
    assert summary["gl_balance_sign"] == "credit balance shown positive"


async def test_other_accounts_and_unknown_periods(me: AsyncClient, source_id: str) -> None:
    bank = await prefilled(me, source_id, "Operating Account", "2026-08")
    assert bank["input"]["gl_balance"] == "250000.00"
    assert bank["input"]["subledger_balance"] is None  # not in the data: entered by hand
    assert bank["source"]["records"]["summary"]["subledger"].startswith("Not in the data")

    missing = await prefilled(me, source_id, "Operating Account", "1999-01")
    assert missing["input"]["gl_balance"] is None
    assert missing["source"]["records"]["summary"]["gl_balance"].startswith("No month-end")


async def test_history_failure_is_shown_on_the_source(
    me: AsyncClient,
    intuit: FakeIntuit,  # noqa: F811 - the fixture imported above
) -> None:
    intuit.reports_fail = True
    await connect(me)

    [source] = (await me.get("/api/v1/data-sources")).json()
    assert source["status"] == "connected"  # the entities synced fine
    assert source["history_status"] == "error"
    assert source["history_error"].startswith("Month-end history couldn't be fetched")
    assert "account_balance" not in source["record_counts"]
