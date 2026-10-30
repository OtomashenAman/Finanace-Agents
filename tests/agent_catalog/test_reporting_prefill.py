"""Board Reporting and FP&A prefilled from the monthly P&L and budget in month-end history."""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.periods import (
    months_of,
    period_end,
    period_options,
    same_period_last_year,
)
from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole
from src.app.data_sources.providers.quickbooks import _budgets, _profit_and_loss
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import REPORTS, FakeIntuit, connect, intuit  # noqa: F401

pytestmark = pytest.mark.usefixtures("synced_agents")


# --- periods ----------------------------------------------------------------------------------


def test_periods() -> None:
    assert months_of("2026-q3") == ["2026-07", "2026-08", "2026-09"]
    assert months_of("2026") == [f"2026-{m:02d}" for m in range(1, 13)]
    assert months_of("Q3 2026") is None
    assert same_period_last_year("2026-Q3") == "2025-Q3"
    assert same_period_last_year("2026-09") == "2025-09"
    assert str(period_end("2026-Q1")) == "2026-03-31"
    months = {f"2025-{m:02d}" for m in range(1, 13)} | {"2026-01", "2026-02"}
    options = period_options(months)
    assert options[:2] == ["2026-02", "2026-01"]
    assert "2026-Q1" not in options  # March is missing
    assert options[-5:] == ["2025-Q4", "2025-Q3", "2025-Q2", "2025-Q1", "2025"]


# --- report parsing ---------------------------------------------------------------------------


def test_profit_and_loss_by_class_and_total() -> None:
    results = {r.business_unit: r for r in _profit_and_loss(REPORTS["ProfitAndLoss"], "2026-09")}

    assert set(results) == {"East", "West", None}
    company = results[None]
    assert company.revenue == Decimal("100000.00")
    assert company.cogs == Decimal("30000.00")
    assert company.operating_expenses == Decimal("20000.00")
    assert company.operating_profit == Decimal("50000.00")
    assert results["East"].revenue == Decimal("60000.00")
    assert company.basis == "actual" and company.external_id == "actual-2026-09-company"


def test_not_specified_is_dropped_only_when_there_are_no_classes() -> None:
    def report(*titles: str) -> dict[str, Any]:
        columns = [{"ColTitle": ""}, *({"ColTitle": t} for t in titles)]
        cells = [{"value": "Total Income"}, *({"value": "100.00"} for _ in titles)]
        row = {"type": "Section", "group": "Income", "Summary": {"ColData": cells}}
        return {"Columns": {"Column": columns}, "Rows": {"Row": [row]}}

    # As the real sandbox returns it: no classes, "Not Specified" is a copy of the total
    alone = _profit_and_loss(report("Not Specified", "TOTAL"), "2026-07")
    assert [r.business_unit for r in alone] == [None]
    # With classes, "Not Specified" is its own slice (transactions without a class)
    mixed = _profit_and_loss(report("East", "Not Specified", "TOTAL"), "2026-07")
    assert [r.business_unit for r in mixed] == ["East", "Not Specified", None]


def test_budgets_add_up_by_month_and_class() -> None:
    accounts = {
        "79": {"AccountType": "Income"},
        "80": {"AccountType": "Expense"},
        "81": {"AccountType": "Other Income"},  # not operating: left out
    }
    lines = [
        {"BudgetDate": "2026-09-01", "Amount": 54000, "AccountRef": {"value": "79"},
         "ClassRef": {"name": "East"}},
        {"BudgetDate": "2026-09-01", "Amount": 36000, "AccountRef": {"value": "79"},
         "ClassRef": {"name": "West"}},
        {"BudgetDate": "2026-09-01", "Amount": 18000, "AccountRef": {"value": "80"}},
        {"BudgetDate": "2026-09-01", "Amount": 500, "AccountRef": {"value": "81"}},
        {"BudgetDate": "2020-01-01", "Amount": 1, "AccountRef": {"value": "79"}},  # outside
    ]  # fmt: skip
    budgets = [
        {"Active": True, "BudgetDetail": lines},
        {"Active": False, "BudgetDetail": lines},
    ]
    results = {r.business_unit: r for r in _budgets(budgets, accounts, {"2026-09"})}

    assert set(results) == {None, "East", "West"}
    assert results[None].revenue == Decimal("90000.00")
    assert results[None].operating_expenses == Decimal("18000.00")
    assert results[None].operating_profit == Decimal("72000.00")
    assert results["East"].revenue == Decimal("54000.00")
    assert results["East"].operating_expenses == Decimal("0.00")
    assert all(r.basis == "budget" for r in results.values())


# --- prefill ----------------------------------------------------------------------------------


@pytest.fixture
async def me(
    make_user: MakeUser,
    db: AsyncSession,
    signed_in_client: ClientFactory,
    intuit: FakeIntuit,  # noqa: F811 - the fixture imported above
) -> AsyncClient:
    user = await make_user("reporting@example.com", UserRole.USER)
    for key in ("board_reporting", "fpa_forecast"):
        await assign(db, user, AgentCapacity.PREPARER, key=key)
    return await signed_in_client(user)


@pytest.fixture
async def source_id(me: AsyncClient) -> str:
    result: str = (await connect(me))["source"][0]
    return result


async def options(client: AsyncClient, key: str, source_id: str) -> Any:
    r = await client.get(f"/api/v1/agents/{key}/prefill-options", params={"source_id": source_id})
    return r.json()


async def prefilled(client: AsyncClient, key: str, source_id: str, **params: str) -> Any:
    runs = f"/api/v1/agents/{key}/runs"
    run = (await client.post(runs)).json()
    r = await client.post(
        f"{runs}/{run['id']}/prefill", json={"source_id": source_id, "params": params}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_board_quarter_against_the_same_quarter_last_year(
    me: AsyncClient, source_id: str, fake_llm: FakeLLM
) -> None:
    periods = (await options(me, "board_reporting", source_id))["reporting_period"]
    quarter = next(
        p for p in periods if "-Q" in p and same_period_last_year(p) in periods
    )  # the latest quarter with last year's in the data

    run = await prefilled(me, "board_reporting", source_id, reporting_period=quarter)
    assert run["input"]["reporting_period"] == quarter
    assert run["input"]["reported_revenue"] == "300000.00"  # 3 x 100,000
    assert run["input"]["operating_profit"] == "150000.00"
    assert run["input"]["prior_period_revenue"] == "300000.00"
    source_ref = run["input"]["source_dataset_id"]
    assert source_ref.startswith(f"QuickBooks Acme Holdings Ltd: P&L {quarter}")
    records = run["source"]["records"]
    assert len(records["months"]) == 3 and len(records["prior_year_months"]) == 3
    assert run["source"]["record_reference"] == f"{quarter} vs {same_period_last_year(quarter)}"

    fake_llm.output["cited_fields"] = ["reported_revenue"]
    values = {**run["input"], "report_name": "Board pack"}
    runs = "/api/v1/agents/board_reporting/runs"
    await me.put(f"{runs}/{run['id']}/input", json={"values": values})
    run = (await me.post(f"{runs}/{run['id']}/analyze")).json()
    codes = {f["code"] for f in run["flags"]}
    assert "SOURCE_REFERENCED" in codes  # filled from the data
    assert codes & {"PERIOD_CLOSED", "PERIOD_NOT_CLOSED"}  # books closed through 2026-08-31


async def test_board_year_without_last_year_in_the_data(me: AsyncClient, source_id: str) -> None:
    periods = (await options(me, "board_reporting", source_id))["reporting_period"]
    year = next(p for p in periods if len(p) == 4)  # 24 months hold one complete year at most

    run = await prefilled(me, "board_reporting", source_id, reporting_period=year)
    assert run["input"]["reported_revenue"] == "1200000.00"  # 12 x 100,000
    assert run["input"]["prior_period_revenue"] is None
    assert run["source"]["records"]["summary"]["prior"].startswith("Not every month of")


async def test_fpa_unit_metric_actual_and_budget(
    me: AsyncClient, source_id: str, fake_llm: FakeLLM
) -> None:
    choices = await options(me, "fpa_forecast", source_id)
    assert choices["business_unit"] == ["Whole company", "East", "West"]
    latest = choices["forecast_period"][0]
    form = (await me.get("/api/v1/agents/fpa_forecast/form")).json()
    metric = next(f for f in form["prefill_fields"] if f["name"] == "metric")
    assert metric["options"] == ["Revenue", "Operating profit", "Operating expenses"]

    east = await prefilled(
        me, "fpa_forecast", source_id, business_unit="East", forecast_period=latest,
        metric="Revenue",
    )  # fmt: skip
    assert east["input"]["business_unit"] == "East"
    assert east["input"]["actual_value"] == "60000.00"
    assert east["input"]["budget_value"] == "54000.00"
    assert east["source"]["record_reference"] == f"Revenue · East · {latest}"

    company = await prefilled(
        me, "fpa_forecast", source_id, business_unit="Whole company", forecast_period=latest,
        metric="Operating profit",
    )  # fmt: skip
    assert company["input"]["actual_value"] == "50000.00"
    assert company["input"]["budget_value"] == "72000.00"  # 90,000 sales budget - 18,000 rent

    bad = await me.post(
        f"/api/v1/agents/fpa_forecast/runs/{east['id']}/prefill",
        json={"source_id": source_id, "params": {"business_unit": "East",
                                                 "forecast_period": latest, "metric": "EBITDA"}},
    )  # fmt: skip
    assert bad.status_code == 422


async def test_fpa_without_a_budget_in_the_data(
    me: AsyncClient,
    intuit: FakeIntuit,  # noqa: F811 - the fixture imported above
    fake_llm: FakeLLM,
) -> None:
    intuit.budgets = []
    source_id = (await connect(me))["source"][0]
    latest = (await options(me, "fpa_forecast", source_id))["forecast_period"][0]
    run = await prefilled(
        me, "fpa_forecast", source_id, business_unit="Whole company", forecast_period=latest,
        metric="Revenue",
    )  # fmt: skip
    assert run["input"]["actual_value"] == "100000.00"
    assert run["input"]["budget_value"] is None
    assert run["source"]["records"]["summary"]["budget"].startswith("No complete budget")

    fake_llm.output["cited_fields"] = ["actual_value"]
    values = {**run["input"], "budget_value": "95000", "scenario_volume_pct": "0",
              "scenario_price_pct": "0", "scenario_cost_pct": "0"}  # fmt: skip
    runs = "/api/v1/agents/fpa_forecast/runs"
    await me.put(f"{runs}/{run['id']}/input", json={"values": values})
    run = (await me.post(f"{runs}/{run['id']}/analyze")).json()
    flags = {f["code"]: f["severity"] for f in run["flags"]}
    assert flags["BUDGET_NOT_IN_DATA"] == "warning"
