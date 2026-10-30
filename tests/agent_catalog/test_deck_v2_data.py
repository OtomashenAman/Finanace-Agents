"""The deck's QuickBooks data contracts, end to end: supplier payments and credits, customer
credits, manual journals, the SOX population and intercompany across two companies."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import User, UserRole
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import SOURCES, FakeIntuit, connect, intuit  # noqa: F401
from tests.entities.test_api import entity, give

pytestmark = pytest.mark.usefixtures("synced_agents", "intuit", "fake_llm")

AGENTS = ("ap_invoice", "ar_collections", "financial_close", "sox_controls", "intercompany")
ACME = {"value": "56", "name": "Acme Cloud Services"}
HARBOR = {"value": "81", "name": "Harbor Distribution"}


@pytest.fixture
def qbo(intuit: FakeIntuit) -> FakeIntuit:  # noqa: F811 - the fixture imported above
    """The fake QuickBooks, to add rows to (`qbo.extra`)."""
    return intuit


@pytest.fixture
async def analyst(make_user: MakeUser, db: AsyncSession) -> User:
    user = await make_user("controller@example.com", UserRole.USER)
    for key in AGENTS:
        await assign(db, user, AgentCapacity.PREPARER, key=key)
    return user


@pytest.fixture
async def me(analyst: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(analyst)


async def analyzed(
    client: AsyncClient, key: str, entity_id: str | None = None, **values: Any
) -> Any:
    runs = f"/api/v1/agents/{key}/runs"
    created = await client.post(runs, json={"entity_id": entity_id} if entity_id else None)
    assert created.status_code == 201, created.text
    run = created.json()
    r = await client.put(f"{runs}/{run['id']}/input", json={"values": values})
    assert r.status_code == 200, r.text
    return (await client.post(f"{runs}/{run['id']}/analyze")).json()


def flags(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["code"]: f for f in run["flags"]}


async def latest_close_period(client: AsyncClient, source_id: str) -> str:
    options = await client.get(
        "/api/v1/agents/financial_close/prefill-options", params={"source_id": source_id}
    )
    period: str = options.json()["close_period"][0]
    return period


# --- AP: supplier payments and credits --------------------------------------------------------


async def test_an_invoice_already_paid_and_unused_supplier_credits_are_flagged(
    me: AsyncClient, qbo: FakeIntuit
) -> None:
    qbo.extra = {
        "BillPayment": [
            {"Id": "900", "DocNumber": "CHK-4410", "VendorRef": ACME, "TotalAmt": 12500.0,
             "TxnDate": "2026-10-20",
             "Line": [{"Amount": 12500.0, "LinkedTxn": [{"TxnId": "145", "TxnType": "Bill"}]}]},
        ],
        "VendorCredit": [
            {"Id": "910", "DocNumber": "VC-12", "VendorRef": ACME, "TotalAmt": 300.0,
             "Balance": 300.0, "TxnDate": "2026-10-02"},
        ],
    }  # fmt: skip
    await connect(me)
    run = await analyzed(
        me, "ap_invoice", supplier="Acme Cloud Services", invoice_number="INV-2048",
        received_amount="12500.00",
    )  # fmt: skip

    assert run["status"] == "analyzed", run
    found = flags(run)
    assert found["ALREADY_PAID"]["severity"] == "high"
    assert "CHK-4410" in found["ALREADY_PAID"]["message"]
    assert found["SUPPLIER_CREDIT_AVAILABLE"]["severity"] == "warning"
    assert "300.00" in found["SUPPLIER_CREDIT_AVAILABLE"]["message"]


def item_line(item: str, qty: int, price: float) -> dict[str, Any]:
    return {"Amount": qty * price, "ItemBasedExpenseLineDetail": {
        "ItemRef": {"value": item, "name": item}, "Qty": qty, "UnitPrice": price}}  # fmt: skip


async def test_an_invoice_is_matched_to_its_po_line_by_line(
    me: AsyncClient, qbo: FakeIntuit
) -> None:
    hosting = {"value": "7", "name": "6100 Cloud Hosting"}
    qbo.extra = {
        "Item": [
            {"Id": "Compute hours", "Name": "Compute hours", "ExpenseAccountRef": hosting},
            {"Id": "Storage TB", "Name": "Storage TB", "ExpenseAccountRef": hosting},
        ],
        "PurchaseOrder": [
            {"Id": "330", "DocNumber": "PO-90", "VendorRef": ACME, "TotalAmt": 12500.0,
             "POStatus": "Open",
             "Line": [item_line("Compute hours", 100, 100.0), item_line("Storage TB", 10, 250.0)]},
        ],
        # Same total as the PO, but storage is billed at 260 and compute short by 10 hours
        "Bill": [
            {"Id": "331", "DocNumber": "INV-5001", "VendorRef": ACME, "TotalAmt": 11600.0,
             "TxnDate": "2026-10-15", "LinkedTxn": [{"TxnId": "330", "TxnType": "PurchaseOrder"}],
             "Line": [item_line("Compute hours", 90, 100.0), item_line("Storage TB", 10, 260.0)]},
        ],
    }  # fmt: skip
    await connect(me)
    run = await analyzed(
        me, "ap_invoice", supplier="Acme Cloud Services", invoice_number="INV-5001",
        received_amount="11600.00",
    )  # fmt: skip

    assert run["status"] == "analyzed", run
    found = flags(run)
    assert (
        "'Storage TB': billed at 260.00 vs 250.00 on PO-90"
        in (found["LINE_PRICE_DIFFERS"]["message"])
    )
    assert "LINE_QUANTITY_OVER" not in found  # 90 of 100 hours: within the order
    assert "LINE_NOT_ON_PO" not in found
    # Coded from the items' expense account (QuickBooks Item.ExpenseAccountRef)
    assert run["input"]["proposed_gl_account"] == "6100 Cloud Hosting"


async def test_each_filled_field_shows_where_it_came_from_until_it_is_changed(
    me: AsyncClient, qbo: FakeIntuit
) -> None:
    source_id = (await connect(me))["source"][0]
    runs = "/api/v1/agents/ap_invoice/runs"
    run = (await me.post(runs)).json()
    run = (
        await me.put(
            f"{runs}/{run['id']}/source", json={"source_id": source_id, "record_id": "145"}
        )
    ).json()
    lineage = run["source"]["field_sources"]
    assert lineage["invoice_total"] == "bill INV-2048"
    assert "received_amount" not in lineage  # not in QuickBooks: the preparer enters it

    # Analyze completes the rest; each value keeps its origin
    values = {**run["input"], "received_amount": "12500.00"}
    await me.put(f"{runs}/{run['id']}/input", json={"values": values})
    run = (await me.post(f"{runs}/{run['id']}/analyze")).json()
    assert run["source"]["field_sources"]["invoice_total"] == "bill INV-2048"

    # A value the preparer changes is theirs, not QuickBooks'
    values = {**run["input"], "invoice_total": "12000.00"}
    run = (await me.put(f"{runs}/{run['id']}/input", json={"values": values})).json()
    assert "invoice_total" not in run["source"]["field_sources"]
    assert run["source"]["field_sources"]["supplier"] == "bill INV-2048"


# --- AR: customer credits ---------------------------------------------------------------------


async def test_unapplied_credit_memos_reduce_the_exposure(me: AsyncClient, qbo: FakeIntuit) -> None:
    qbo.extra = {
        "CreditMemo": [
            {"Id": "920", "DocNumber": "CM-7", "CustomerRef": HARBOR, "TotalAmt": 250.0,
             "RemainingCredit": 200.0, "TxnDate": "2026-10-05"},
        ]
    }  # fmt: skip
    await connect(me)
    run = await analyzed(
        me, "ar_collections", customer="Harbor Distribution", open_dispute=False,
        strategic_account=False,
    )  # fmt: skip

    assert run["status"] == "analyzed", run
    credit = flags(run)["UNAPPLIED_CREDITS"]
    assert "200.00" in credit["message"] and "800.00" in credit["message"]  # 1,000 - 200


async def test_an_open_dispute_never_gets_a_customer_reminder(
    me: AsyncClient, fake_llm: FakeLLM
) -> None:
    await connect(me)
    fake_llm.output["draft_message"] = "Internal: resolve the pallet dispute first."
    await analyzed(
        me, "ar_collections", customer="Harbor Distribution", open_dispute=True,
        strategic_account=False,
    )  # fmt: skip

    draft = fake_llm.schemas[-1].model_fields["draft_message"].description or ""
    assert draft.startswith("Internal note to the collections lead")


# --- Close: manual journal drilldown ----------------------------------------------------------


async def test_an_unexplained_difference_lists_the_manual_journals(
    me: AsyncClient, qbo: FakeIntuit
) -> None:
    source_id = (await connect(me))["source"][0]
    period = await latest_close_period(me, source_id)
    qbo.extra = {
        "JournalEntry": [
            {"Id": "77", "DocNumber": "JE-1005", "TxnDate": f"{period}-28", "Line": [
                {"Id": "0", "Amount": 1000.0, "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": "84", "name": "Accounts Receivable (A/R)"}}},
                {"Id": "1", "Amount": 1000.0, "JournalEntryLineDetail": {
                    "PostingType": "Credit", "AccountRef": {"value": "79", "name": "Sales"}}},
            ]},
        ]
    }  # fmt: skip
    await me.post(f"{SOURCES}/{source_id}/sync")

    run = await analyzed(
        me, "financial_close", gl_account="Accounts Receivable (A/R)", close_period=period,
        materiality_threshold="500",
    )  # fmt: skip
    assert run["status"] == "analyzed", run
    journals = flags(run)["MANUAL_JOURNALS"]
    assert "JE-1005 (1,000.00)" in journals["message"]
    assert run["input"]["accounting_basis"] == "Accrual"  # the basis the books were read on


# --- SOX: the payment population --------------------------------------------------------------


async def test_the_sox_population_comes_from_supplier_payments(
    me: AsyncClient, qbo: FakeIntuit
) -> None:
    def payment(pid: str, amount: float, day: str) -> dict[str, Any]:
        return {"Id": pid, "DocNumber": f"CHK-{pid}", "VendorRef": ACME, "TotalAmt": amount,
                "TxnDate": day, "Line": []}  # fmt: skip

    qbo.extra = {
        "BillPayment": [
            payment("1", 15000.0, "2026-09-03"),
            payment("2", 12000.0, "2026-09-17"),
            payment("3", 500.0, "2026-09-18"),  # below the threshold
            payment("4", 30000.0, "2026-08-30"),  # another period
        ]
    }
    await connect(me)
    run = await analyzed(
        me, "sox_controls", control_id="AP-10K", control_owner="AP Manager",
        test_period="2026-09", population_threshold="10000", items_tested="2",
        exceptions_found="0",
    )  # fmt: skip

    assert run["status"] == "analyzed", run
    assert run["input"]["population_count"] == 2
    population = run["source"]["records"]["population"]
    assert [p["payment_number"] for p in population] == ["CHK-1", "CHK-2"]
    assert "approval system" in run["source"]["records"]["summary"]["approval_evidence"]


# --- Intercompany: two QuickBooks companies ---------------------------------------------------


async def test_intercompany_reads_each_side_from_its_own_company(
    me: AsyncClient,
    analyst: User,
    qbo: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
) -> None:
    adm = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    us = await entity(adm, "US01", "US Operations")
    uk = await entity(adm, "UK01", "UK Operations")
    await give(adm, analyst, us, uk)
    uk_customer = {"value": "91", "name": "UK Operations"}
    us_vendor = {"value": "92", "name": "US01"}
    qbo.extra = {
        # The US books bill the UK entity by name; the UK books owe the US entity by code
        "Invoice": [
            {"Id": "880", "DocNumber": "IC-1", "CustomerRef": uk_customer, "TotalAmt": 50000.0,
             "Balance": 50000.0, "TxnDate": "2026-10-01", "Line": []},
        ],
        "Bill": [
            {"Id": "881", "DocNumber": "IC-1", "VendorRef": us_vendor, "TotalAmt": 49000.0,
             "Balance": 49000.0, "TxnDate": "2026-10-01", "Line": []},
        ],
    }  # fmt: skip
    us_books = (await connect(me))["source"][0]
    uk_books = (await connect(me, realm="9130350000000002"))["source"][0]
    await me.patch(f"{SOURCES}/{us_books}", json={"entity_id": us["id"]})
    await me.patch(f"{SOURCES}/{uk_books}", json={"entity_id": uk["id"]})

    run = await analyzed(
        me, "intercompany", sending_entity="US01", receiving_entity="UK01", currency="USD",
        translation_rate="1", matching_tolerance="100", entity_id=us["id"],
    )  # fmt: skip
    assert run["status"] == "analyzed", run
    assert run["input"]["intercompany_ar"] == "50000.00"
    assert run["input"]["counterparty_ap"] == "49000.00"
    notes = [f["message"] for f in run["flags"] if f["code"] == "FILLED_FROM_DATA"]
    assert any("open invoices to UK01" in n for n in notes)
    assert any("open bills from US01" in n for n in notes)


async def test_intercompany_needs_each_entity_linked_to_its_books(me: AsyncClient) -> None:
    await connect(me)
    run = await analyzed(
        me, "intercompany", sending_entity="US01", receiving_entity="UK01", currency="USD",
        translation_rate="1", matching_tolerance="100",
    )  # fmt: skip
    assert run["status"] == "validation_failed"
    messages = [e["message"] for e in run["validation_errors"]]
    assert any("No QuickBooks company is linked to US01" in m for m in messages)
