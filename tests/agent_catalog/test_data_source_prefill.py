"""Cash Application, Expense Audit and AR Collections prefilled from the preparer's QuickBooks."""

from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ar_collections.agent import exposure
from src.app.agent_catalog.agents.cash_application.agent import candidate_invoice
from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import UserRole
from src.app.common.clock import utcnow
from src.app.data_sources.records import Invoice, Payment
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import FakeIntuit, connect, intuit  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("synced_agents", "intuit")

AGENTS = ("cash_application", "expense_audit", "ar_collections")


@pytest.fixture
async def me(make_user: MakeUser, db: AsyncSession, signed_in_client: ClientFactory) -> AsyncClient:
    user = await make_user("cash.analyst@example.com", UserRole.USER)
    for key in AGENTS:
        await assign(db, user, AgentCapacity.PREPARER, key=key)
    return await signed_in_client(user)


async def prefilled(client: AsyncClient, key: str, record_id: str) -> dict[str, Any]:
    """A new run of `key` prefilled from the QuickBooks record `record_id`."""
    source_id = (await connect(client))["source"][0]
    runs = f"/api/v1/agents/{key}/runs"
    run = (await client.post(runs)).json()
    r = await client.put(
        f"{runs}/{run['id']}/source", json={"source_id": source_id, "record_id": record_id}
    )
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    return result


async def analyzed(client: AsyncClient, key: str, run: dict[str, Any], **extra: Any) -> Any:
    runs = f"/api/v1/agents/{key}/runs"
    if extra:
        values = {**run["input"], **extra}
        r = await client.put(f"{runs}/{run['id']}/input", json={"values": values})
        assert r.status_code == 200, r.text
    r = await client.post(f"{runs}/{run['id']}/analyze")
    assert r.json()["status"] == "analyzed", r.json()
    return r.json()


def codes(run: dict[str, Any]) -> dict[str, str]:
    return {f["code"]: f["severity"] for f in run["flags"]}


# --- Cash Application -------------------------------------------------------------------------


async def test_unapplied_payment_finds_the_invoice_its_memo_names(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await prefilled(me, "cash_application", "402")

    assert run["input"] == {
        "customer": "Harbor Distribution",
        "payment_reference": "WIRE-2901",
        "payment_amount": "900.00",
        "candidate_invoice_number": "INV-8021",
        "invoice_open_amount": "1000.00",
        "reference_verified": True,  # the memo names the invoice
        "remittance_advice": "Short paid INV-8021: damaged pallet",
    }
    assert set(run["source"]["records"]) == {"payment", "invoice"}

    run = await analyzed(me, "cash_application", run)
    found = codes(run)
    assert found["INVOICE_IN_LEDGER"] == "pass"
    assert found["SHORT_PAYMENT"] == "warning"
    assert found["DEDUCTION_REVIEW"] == "high"
    assert "AMBIGUOUS_REMITTANCE" not in found  # the memo explains it


async def test_applied_payment_restores_the_open_amount_before_it(me: AsyncClient) -> None:
    run = await prefilled(me, "cash_application", "401")

    # INV-8000's balance is 0 after this payment; before it, 500.00 was open
    assert run["input"]["candidate_invoice_number"] == "INV-8000"
    assert run["input"]["invoice_open_amount"] == "500.00"
    assert run["input"]["reference_verified"] is True


async def test_invoice_of_another_customer_is_an_exception(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await prefilled(me, "cash_application", "402")
    run = await analyzed(me, "cash_application", run, customer="Quiet Customer")

    assert codes(run)["INVOICE_CUSTOMER_MISMATCH"] == "high"


def invoice(number: str, open_amount: str, customer: str = "Harbor") -> Invoice:
    return Invoice(
        external_id=number, doc_number=number, customer_name=customer, total=open_amount,
        balance=open_amount,
    )  # fmt: skip


class FakeData:
    """FinanceData with fixed invoices (candidate_invoice only uses find and records)."""

    def __init__(self, invoices: list[Invoice]) -> None:
        self.invoices = invoices

    async def find(self, model: Any, record_type: Any, reference: str) -> Invoice | None:
        return next((i for i in self.invoices if i.doc_number == reference), None)

    async def records(self, model: Any, record_type: Any, counterparty: str) -> list[Invoice]:
        return [i for i in self.invoices if i.customer_name == counterparty]


@pytest.mark.parametrize(
    ("memo", "invoices", "expected"),
    [
        # Same amount, only one: proposed but not verified
        (None, [invoice("INV-1", "900"), invoice("INV-2", "50")], ("INV-1", False)),
        # Two with the same amount: the preparer picks
        (None, [invoice("INV-1", "900"), invoice("INV-2", "900")], (None, False)),
        # INV-1 is not INV-10
        ("Paying INV-10", [invoice("INV-1", "900"), invoice("INV-10", "70")], ("INV-10", True)),
        # Another customer's invoice is never proposed
        (None, [invoice("INV-9", "900", customer="Other")], (None, False)),
    ],
)
async def test_candidate_invoice_rules(
    memo: str | None, invoices: list[Invoice], expected: tuple[str | None, bool]
) -> None:
    payment = Payment(
        external_id="1", reference_number="WIRE-1", customer_name="Harbor", total="900", memo=memo
    )
    found, verified = await candidate_invoice(payment, FakeData(invoices))  # type: ignore[arg-type]
    assert (found.doc_number if found else None, verified) == expected


# --- Expense Audit ----------------------------------------------------------------------------


async def test_card_charge_prefills_with_the_category_limit_and_catches_a_double_charge(
    me: AsyncClient, make_user: MakeUser, signed_in_client: ClientFactory, fake_llm: FakeLLM
) -> None:
    admin = await signed_in_client(await make_user("cfo@example.com", UserRole.FINANCE_ADMIN))
    r = await admin.put(
        "/api/v1/admin/governance/policies/expense_audit",
        json={"values": {"category_limits": {"Lodging": "200"}, "default_limit": "50"}},
    )
    assert r.status_code == 200, r.text
    fake_llm.output["cited_fields"] = ["claim_amount"]
    fake_llm.output["draft_message"] = "Hello, please explain the hotel charge."

    run = await prefilled(me, "expense_audit", "501")
    assert run["input"] == {
        "employee": None,  # not in the source: the preparer fills it in
        "merchant": "Northbridge Hotel",
        "claim_amount": "285.00",
        "policy_limit": "200.00",  # the Lodging limit, not the default
        "receipt_total": None,
        "receipt_provided": True,  # a file is attached in QuickBooks
        "card_transaction_id": "501",
        "prior_card_transaction_ids": None,
    }

    run = await analyzed(me, "expense_audit", run, employee="Jordan Smith", receipt_total="285")
    found = codes(run)
    assert found["DUPLICATE_CHARGE"] == "high"  # 502: same merchant, amount and date
    assert found["POLICY_LIMIT_EXCEEDED"] == "high"
    assert run["headline"] == "Duplicate card transaction"

    claim = await analyzed(me, "expense_audit", run, claim_amount="250")
    assert codes(claim)["CLAIM_DIFFERS_FROM_CHARGE"] == "warning"


async def test_bad_category_limits_are_rejected(
    make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    admin = await signed_in_client(await make_user("cfo@example.com", UserRole.FINANCE_ADMIN))
    for limits in ({"Meals": "-5"}, {" ": "10"}, {"Meals": "1.234"}):
        r = await admin.put(
            "/api/v1/admin/governance/policies/expense_audit",
            json={"values": {"category_limits": limits}},
        )
        assert r.status_code == 422, limits


# --- AR Collections ---------------------------------------------------------------------------


async def test_customer_prefills_balance_aging_and_late_history(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    run = await prefilled(me, "ar_collections", "81")

    overdue = (utcnow().date() - date(2026, 9, 30)).days
    assert run["input"]["customer"] == "Harbor Distribution"
    assert run["input"]["open_balance"] == "1000.00"  # INV-8021; INV-8000 is paid
    assert run["input"]["days_overdue"] == overdue
    assert run["input"]["previous_late_payments"] == 1  # INV-8000 paid 5 days late
    assert run["input"]["open_dispute"] is False  # not in the source: left as is
    assert run["source"]["records"]["oldest_open_invoice"]["doc_number"] == "INV-8021"

    fake_llm.output["cited_fields"] = ["open_balance"]
    fake_llm.output["draft_message"] = "Dear Harbor Distribution, a reminder about INV-8021."
    run = await analyzed(me, "ar_collections", run)
    assert run["narrative"]["output"]["draft_message"].startswith("Dear Harbor")


def test_exposure_from_invoices() -> None:
    today = date(2026, 10, 21)
    invoices = [
        Invoice(external_id="1", doc_number="A", customer_name="C", total="100", balance="100",
                due_date=date(2026, 10, 1)),
        Invoice(external_id="2", doc_number="B", customer_name="C", total="50", balance="20",
                due_date=date(2026, 9, 1)),
        # No balance column: paid (has a paid date), late
        Invoice(external_id="3", doc_number="D", customer_name="C", total="70",
                due_date=date(2026, 8, 1), paid_date=date(2026, 8, 9)),
        # Not due yet
        Invoice(external_id="4", doc_number="E", customer_name="C", total="30",
                due_date=date(2026, 11, 1)),
    ]  # fmt: skip
    result = exposure(invoices, today)

    assert str(result.open_balance) == "150.00"  # 100 + 20 + 30
    assert result.days_overdue == 50  # B, due 09-01
    assert result.late_payments == 1
    assert result.oldest_open is not None and result.oldest_open.doc_number == "B"
