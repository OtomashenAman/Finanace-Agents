"""Treasury prefilled from the preparer's data: bank balances, open invoices and bills."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.treasury_cash.agent import cash_position
from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole
from src.app.data_sources.records import Account, Bill, Invoice
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import connect, intuit  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("synced_agents", "intuit")

RUNS = "/api/v1/agents/treasury_cash/runs"
TODAY = date(2026, 10, 21)


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


def test_cash_position_is_conservative() -> None:
    accounts = [
        Account(external_id="1", name="Operating", account_type="Bank", current_balance="1000"),
        Account(external_id="2", name="Payroll", account_type="Bank", current_balance="-50"),
        Account(external_id="3", name="Cloud Hosting", account_type="Expense"),
        Account(external_id="4", name="Savings", account_type="Bank"),  # balance unknown
    ]
    invoices = [
        Invoice(
            external_id="a",
            doc_number="A",
            customer_name="C",
            total="100",
            balance="100",
            due_date=days(5),
        ),
        Invoice(
            external_id="b",
            doc_number="B",
            customer_name="C",
            total="200",
            balance="200",
            due_date=days(-1),
        ),  # overdue: not counted, reported
        Invoice(
            external_id="c",
            doc_number="C",
            customer_name="C",
            total="300",
            balance="300",
            due_date=days(31),
        ),  # after the horizon
        Invoice(external_id="d", doc_number="D", customer_name="C", total="40"),  # no due date
        Invoice(
            external_id="e",
            doc_number="E",
            customer_name="C",
            total="70",
            balance="0",
            due_date=days(3),
        ),  # paid
    ]
    bills = [
        Bill(external_id="x", doc_number="X", vendor_name="V", total="500", due_date=days(-10)),
        Bill(external_id="y", doc_number="Y", vendor_name="V", total="80", balance="30",
             due_date=days(30)),
        Bill(external_id="z", doc_number="Z", vendor_name="V", total="900", due_date=days(60)),
    ]  # fmt: skip
    position = cash_position(accounts, invoices, bills, TODAY, 30)

    assert [a.name for a in position.banks] == ["Operating", "Payroll"]
    assert position.opening_cash == Decimal("950.00")
    assert [i.doc_number for i in position.invoices_due] == ["A", "D"]
    assert position.inflows == Decimal("140.00")
    assert position.overdue_receivables == Decimal("200.00")
    # Overdue payables still have to be paid: counted
    assert [b.doc_number for b in position.bills_due] == ["X", "Y"]
    assert position.outflows == Decimal("530.00")


@pytest.fixture
async def me(make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory) -> AsyncClient:
    user = await make_user("treasury@example.com", UserRole.USER)
    await assign(db, user, AgentCapacity.PREPARER, key="treasury_cash")
    await assign(db, user, AgentCapacity.PREPARER, key="ap_invoice")
    return await signed_in_client(user)


async def prefill(client: AsyncClient, source_id: str, run_id: str, **params: Any) -> Any:
    return await client.post(
        f"{RUNS}/{run_id}/prefill", json={"source_id": source_id, "params": params}
    )


async def test_form_offers_prefill_parameters(me: AsyncClient) -> None:
    form = (await me.get("/api/v1/agents/treasury_cash/form")).json()
    assert [(f["name"], f["kind"], f["default"]) for f in form["prefill_fields"]] == [
        ("forecast_horizon_days", "number", 30)
    ]
    ap = (await me.get("/api/v1/agents/ap_invoice/form")).json()
    assert ap["prefill_fields"] == []  # AP prefills from one picked bill instead


async def test_prefill_from_quickbooks_then_analyze(me: AsyncClient, fake_llm: FakeLLM) -> None:
    source_id = (await connect(me))["source"][0]
    run = (await me.post(RUNS)).json()

    r = await prefill(me, source_id, run["id"], forecast_horizon_days=30)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["input"]["opening_cash"] == "250000.00"  # the Operating bank account
    assert run["input"]["expected_inflows"] == "400.00"  # INV-9001, due in 10 days
    assert run["input"]["expected_outflows"] == "12500.00"  # bill INV-2048, no due date
    assert run["input"]["forecast_horizon_days"] == 30
    assert run["input"]["currency"] is None  # not from the data: the preparer enters it

    source = run["source"]
    assert source["record_type"] == "data"
    assert source["record_reference"].startswith("Next 30 days from ")
    assert source["records"]["parameters"] == {"forecast_horizon_days": 30}
    summary = source["records"]["summary"]
    assert summary["overdue_receivables_not_counted"] == "1000.00"  # INV-8021
    assert summary["bank_accounts"] == 1 and summary["invoices_due"] == 1
    assert [i["doc_number"] for i in source["records"]["invoices_due"]] == ["INV-9001"]
    assert [i["doc_number"] for i in source["records"]["overdue_invoices"]] == ["INV-8021"]
    assert [b["doc_number"] for b in source["records"]["bills_due"]] == ["INV-2048"]

    fake_llm.output["cited_fields"] = ["opening_cash"]
    values = {**run["input"], "currency": "USD", "minimum_liquidity_buffer": "100000"}
    await me.put(f"{RUNS}/{run['id']}/input", json={"values": values})
    run = (await me.post(f"{RUNS}/{run['id']}/analyze")).json()
    assert run["status"] == "analyzed", run
    flags = {f["code"]: f for f in run["flags"]}
    assert flags["OVERDUE_RECEIVABLES"]["severity"] == "warning"
    assert flags["OVERDUE_RECEIVABLES"]["message"].startswith("1,000.00 of receivables (1 invoice)")
    assert flags["LIQUIDITY_BUFFER_MET"]["severity"] == "pass"  # 237,900 closing vs 100,000

    # A shorter horizon is a new prefill: the snapshot follows it
    run = (await prefill(me, source_id, run["id"], forecast_horizon_days=5)).json()
    assert run["status"] == "draft"  # the analysis no longer applies
    assert run["input"]["expected_inflows"] == "0.00"  # INV-9001 is due after 5 days


async def test_prefill_parameters_are_validated(me: AsyncClient) -> None:
    source_id = (await connect(me))["source"][0]
    run = (await me.post(RUNS)).json()
    for bad in (0, 731, "soon"):
        r = await prefill(me, source_id, run["id"], forecast_horizon_days=bad)
        assert r.status_code == 422, bad
        assert r.json()["detail"][0]["loc"][-1] == "forecast_horizon_days"

    # An agent that prefills from one record has no parameters
    ap_run = (await me.post("/api/v1/agents/ap_invoice/runs")).json()
    r = await me.post(
        f"/api/v1/agents/ap_invoice/runs/{ap_run['id']}/prefill",
        json={"source_id": source_id, "params": {}},
    )
    assert r.status_code == 409


async def test_cannot_prefill_from_someone_elses_source(
    me: AsyncClient, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    other = await signed_in_client(await make_user("other@example.com"))
    their_source = (await connect(other))["source"][0]
    run = (await me.post(RUNS)).json()
    assert (await prefill(me, their_source, run["id"])).status_code == 404
