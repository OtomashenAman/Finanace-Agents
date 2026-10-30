"""Revenue Recognition and Lease Accounting prefilled from the preparer's QuickBooks."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole
from tests.agent_catalog.test_data_source_prefill import analyzed, codes, prefilled
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import FakeIntuit, intuit  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("synced_agents")

AGENTS = ("revenue_recognition", "lease_accounting")

FUTURA = {"value": "90", "name": "Futura Technologies"}
CENTRAL = {"value": "91", "name": "Central Offices"}


def sales_line(item: str, amount: float, service_date: str) -> dict[str, Any]:
    return {
        "DetailType": "SalesItemLineDetail",
        "Amount": amount,
        "SalesItemLineDetail": {
            "ItemRef": {"value": "1", "name": item},
            "ServiceDate": service_date,
        },
    }


def rent_bill(bill_id: str, number: str, amount: float, day: str) -> dict[str, Any]:
    return {
        "Id": bill_id,
        "DocNumber": number,
        "VendorRef": CENTRAL,
        "TotalAmt": amount,
        "TxnDate": day,
        "Line": [
            {"AccountBasedExpenseLineDetail": {"AccountRef": {"value": "80", "name": "Rent"}}}
        ],
    }


@pytest.fixture
def books(intuit: FakeIntuit) -> FakeIntuit:  # noqa: F811 - the fixture
    intuit.extra = {
        "Invoice": [
            {
                "Id": "650",
                "DocNumber": "CTR-2026-091",
                "CustomerRef": FUTURA,
                "TotalAmt": 120000.0,
                "Balance": 120000.0,
                "TxnDate": "2026-01-01",
                "Line": [
                    sales_line("Hosting", 90000.0, "2026-01-01"),
                    sales_line("Support", 30000.0, "2026-12-01"),
                    {"DetailType": "SubTotalLineDetail", "Amount": 120000.0},
                ],
            }
        ],
        "Bill": [
            rent_bill("160", "RENT-09", 5000.0, "2026-09-01"),
            rent_bill("161", "RENT-10", 5000.0, "2026-10-01"),
        ],
    }
    return intuit


@pytest.fixture
async def me(
    make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory, books: FakeIntuit
) -> AsyncClient:
    user = await make_user("contracts@example.com", UserRole.USER)
    for key in AGENTS:
        await assign(db, user, AgentCapacity.PREPARER, key=key)
    return await signed_in_client(user)


def filled(run: dict[str, Any]) -> dict[str, Any]:
    """The input values the prefill set (the rest stay empty for the preparer)."""
    return {k: v for k, v in run["input"].items() if v is not None}


# --- Revenue Recognition ----------------------------------------------------------------------


async def test_contract_invoice_fills_the_contract_facts(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await prefilled(me, "revenue_recognition", "650")

    assert filled(run) == {
        "customer": "Futura Technologies",
        "contract_id": "CTR-2026-091",
        "contract_total": "120000.00",
        "service_term_months": 12,  # service dates Jan to Dec
        "performance_obligations": "Hosting: 90,000.00\nSupport: 30,000.00",
    }

    run = await analyzed(me, "revenue_recognition", run)
    found = codes(run)
    assert found["MULTIPLE_OBLIGATIONS"] == "high"
    assert found["CONTRACT_INVOICE_FOUND"] == "pass"
    assert "INVOICED_DIFFERS_FROM_CONTRACT" not in found


async def test_invoice_of_another_customer_is_an_exception(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await prefilled(me, "revenue_recognition", "650")
    run = await analyzed(me, "revenue_recognition", run, customer="Someone Else")

    assert codes(run)["INVOICE_CUSTOMER_MISMATCH"] == "high"


async def test_invoice_without_lines_leaves_term_and_obligations_open(me: AsyncClient) -> None:
    run = await prefilled(me, "revenue_recognition", "601")  # INV-8021: no sales lines

    assert filled(run) == {
        "customer": "Harbor Distribution",
        "contract_id": "INV-8021",
        "contract_total": "1000.00",
    }


async def test_second_run_on_a_contract_points_to_the_first(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    first = await prefilled(me, "revenue_recognition", "650")
    await analyzed(me, "revenue_recognition", first)
    runs = "/api/v1/agents/revenue_recognition/runs"
    second = (await me.post(runs)).json()
    r = await me.put(f"{runs}/{second['id']}/input", json={"values": filled(first)})
    assert r.status_code == 200, r.text
    second = await analyzed(me, "revenue_recognition", r.json())

    assert codes(second)["CONTRACT_ANALYZED_BEFORE"] == "warning"


# --- Lease Accounting -------------------------------------------------------------------------

LEASE_TERMS = {
    "leased_asset": "Headquarters space",
    "remaining_term_months": 24,
    "annual_discount_rate": "6",
}


async def test_rent_bill_fills_lessor_and_payment(me: AsyncClient, fake_llm: FakeLLM) -> None:
    run = await prefilled(me, "lease_accounting", "161")

    assert filled(run) == {"lessor": "Central Offices", "monthly_payment": "5000.00"}

    run = await analyzed(me, "lease_accounting", run, **LEASE_TERMS)
    assert codes(run)["PAYMENT_MATCHES_BILLS"] == "pass"


async def test_payment_that_differs_from_the_latest_bill(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await prefilled(me, "lease_accounting", "161")
    run = await analyzed(me, "lease_accounting", run, **LEASE_TERMS, monthly_payment="5200")

    assert codes(run)["PAYMENT_DIFFERS_FROM_BILLS"] == "warning"


async def test_lessor_without_bills(me: AsyncClient, fake_llm: FakeLLM) -> None:
    run = await prefilled(me, "lease_accounting", "161")
    run = await analyzed(me, "lease_accounting", run, **LEASE_TERMS, lessor="Other Landlord")

    assert codes(run)["NO_LESSOR_BILLS"] == "warning"
