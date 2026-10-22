import json
import urllib.parse
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import Agent, AgentAssignment, AgentCapacity
from src.app.auth.models import User, UserRole
from src.app.common.clock import utcnow
from src.app.data_sources import crypto
from src.app.data_sources.models import DataSource, SourceStatus
from src.app.data_sources.providers import quickbooks as qb
from tests.conftest import ClientFactory, FakeLLM, MakeUser

SOURCES = "/api/v1/data-sources"
APP = {"client_id": "ABclient", "client_secret": "super-secret", "environment": "sandbox"}
RUNS = "/api/v1/agents/ap_invoice/runs"
REALM = "9130350000000001"

pytestmark = pytest.mark.usefixtures("synced_agents")


HARBOR = {"value": "81", "name": "Harbor Distribution"}
QUIET = {"value": "82", "name": "Quiet Customer"}
IN_10_DAYS = (utcnow().date() + timedelta(days=10)).isoformat()
HOTEL = {"value": "90", "name": "Northbridge Hotel", "type": "Vendor"}
LODGING = [{"AccountBasedExpenseLineDetail": {"AccountRef": {"value": "9", "name": "Lodging"}}}]

# Customers, invoices, payments and card purchases, as QuickBooks returns them
RECEIVABLES_AND_EXPENSES: dict[str, list[dict[str, Any]]] = {
    "Customer": [
        {"Id": "81", "DisplayName": "Harbor Distribution", "Active": True, "Balance": 1000.0},
        {"Id": "82", "DisplayName": "Quiet Customer", "Active": True, "Balance": 0},
    ],
    "Invoice": [
        # Open and overdue
        {"Id": "601", "DocNumber": "INV-8021", "CustomerRef": HARBOR, "TotalAmt": 1000.0,
         "Balance": 1000.0, "TxnDate": "2026-09-01", "DueDate": "2026-09-30"},
        # Paid five days late (due 08-15, paid 08-20 by payment 401)
        {"Id": "600", "DocNumber": "INV-8000", "CustomerRef": HARBOR, "TotalAmt": 500.0,
         "Balance": 0, "TxnDate": "2026-07-16", "DueDate": "2026-08-15"},
        # Due in 10 days: inside a 30-day treasury horizon
        {"Id": "602", "DocNumber": "INV-9001", "CustomerRef": QUIET, "TotalAmt": 400.0,
         "Balance": 400.0, "TxnDate": "2026-10-01", "DueDate": IN_10_DAYS},
    ],
    "Payment": [
        # Applied to INV-8000 in QuickBooks
        {"Id": "401", "PaymentRefNum": "CHK-100", "CustomerRef": HARBOR, "TotalAmt": 500.0,
         "TxnDate": "2026-08-20", "UnappliedAmt": 0,
         "Line": [{"Amount": 500.0, "LinkedTxn": [{"TxnId": "600", "TxnType": "Invoice"}]}]},
        # Not applied yet; the memo names the invoice
        {"Id": "402", "PaymentRefNum": "WIRE-2901", "CustomerRef": HARBOR, "TotalAmt": 900.0,
         "TxnDate": "2026-10-15", "UnappliedAmt": 900.0,
         "PrivateNote": "Short paid INV-8021: damaged pallet", "Line": []},
    ],
    "Purchase": [
        {"Id": "501", "EntityRef": HOTEL, "TotalAmt": 285.0, "TxnDate": "2026-10-02",
         "PaymentType": "CreditCard", "Line": LODGING},
        # Same merchant, amount and date: a possible double charge
        {"Id": "502", "EntityRef": HOTEL, "TotalAmt": 285.0, "TxnDate": "2026-10-02",
         "PaymentType": "CreditCard", "Line": LODGING},
    ],
    # A receipt is attached to purchase 501 only
    "Attachable": [
        {"Id": "700", "AttachableRef": [{"EntityRef": {"type": "Purchase", "value": "501"}}]},
    ],
}  # fmt: skip


def _cell(value: str, account_id: str | None = None) -> dict[str, str]:
    return {"value": value, "id": account_id} if account_id else {"value": value}


# Month-end reports, as QuickBooks returns them (the same figures for every month)
REPORTS: dict[str, dict[str, Any]] = {
    "TrialBalance": {
        "Header": {"ReportName": "TrialBalance"},
        "Rows": {
            "Row": [
                {"ColData": [_cell("Operating Account", "3"), _cell("250,000.00"), _cell("")]},
                {"ColData": [_cell("Accounts Receivable (A/R)", "84"), _cell("120000.00"),
                             _cell("")]},
                {"ColData": [_cell("Accounts Payable (A/P)", "33"), _cell(""), _cell("49000.00")]},
                {"type": "Section", "group": "GrandTotal",
                 "Summary": {"ColData": [_cell("TOTAL"), _cell("370000.00"), _cell("49000.00")]}},
            ]
        },
    },
    "AgedReceivables": {
        "Rows": {
            "Row": [
                {"ColData": [_cell("Harbor Distribution", "81"), _cell("1000.00"),
                             _cell("119000.00")]},
                {"type": "Section", "group": "GrandTotal",
                 "Summary": {"ColData": [_cell("TOTAL"), _cell("1000.00"), _cell("119000.00")]}},
            ]
        },
    },
    # Per class (business unit) and the company total, the same every month
    "ProfitAndLoss": {
        "Columns": {"Column": [{"ColTitle": ""}, {"ColTitle": "East"}, {"ColTitle": "West"},
                               {"ColTitle": "TOTAL"}]},
        "Rows": {
            "Row": [
                {"type": "Section", "group": "Income", "Summary": {"ColData": [
                    _cell("Total Income"), _cell("60000.00"), _cell("40000.00"),
                    _cell("100000.00")]}},
                {"type": "Section", "group": "COGS", "Summary": {"ColData": [
                    _cell("Total Cost of Goods Sold"), _cell("18000.00"), _cell("12000.00"),
                    _cell("30000.00")]}},
                {"type": "Section", "group": "Expenses", "Summary": {"ColData": [
                    _cell("Total Expenses"), _cell("12000.00"), _cell("8000.00"),
                    _cell("20000.00")]}},
                {"type": "Section", "group": "NetOperatingIncome", "Summary": {"ColData": [
                    _cell("Net Operating Income"), _cell("30000.00"), _cell("20000.00"),
                    _cell("50000.00")]}},
            ]
        },
    },
    # No grand total row: the rows are added up
    "AgedPayables": {
        "Rows": {
            "Row": [
                {"ColData": [_cell("Acme Cloud Services", "56"), _cell("40000.00")]},
                {"ColData": [_cell("Old Supplier", "57"), _cell("9000.00")]},
            ]
        },
    },
}  # fmt: skip


def monthly_budget() -> list[dict[str, Any]]:
    """A budget for every month of the history window: Sales by class, Rent for the company."""
    lines = []
    for period in qb.history_periods(utcnow().date()):
        day = f"{period}-01"
        lines += [
            {"BudgetDate": day, "Amount": 54000, "AccountRef": {"value": "79"},
             "ClassRef": {"value": "1", "name": "East"}},
            {"BudgetDate": day, "Amount": 36000, "AccountRef": {"value": "79"},
             "ClassRef": {"value": "2", "name": "West"}},
            {"BudgetDate": day, "Amount": 18000, "AccountRef": {"value": "80"}},
        ]  # fmt: skip
    return [
        {"Id": "1", "Name": "FY budget", "Active": True, "BudgetDetail": lines},
        # Inactive budgets are ignored
        {"Id": "2", "Name": "Old draft", "Active": False, "BudgetDetail": lines},
    ]


class FakeIntuit:
    """Intuit's OAuth and accounting API, as far as the app uses them."""

    def __init__(self) -> None:
        self.issued = 0
        self.revoked: list[str] = []
        self.refresh_rejected = False
        self.note = "Entered by AP"
        self.sync_token = 3
        self.updates = 0
        self.created: list[dict[str, Any]] = []
        self.report_calls = 0
        self.reports_fail = False
        self.budgets = monthly_budget()
        self.vendors: list[dict[str, Any]] = [
            {"Id": "56", "DisplayName": "Acme Cloud Services", "Active": True},
            {"Id": "57", "DisplayName": "Old Supplier", "Active": False},
        ]
        # More query rows by entity, added by a test (e.g. {"Invoice": [...]})
        self.extra: dict[str, list[dict[str, Any]]] = {}

    def _tokens(self) -> httpx.Response:
        self.issued += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"at-{self.issued}",
                "refresh_token": f"rt-{self.issued}",
                "expires_in": 3600,
            },
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == qb.TOKEN_URL:
            form = urllib.parse.parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                if form["code"] != ["good-code"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return self._tokens()
            if self.refresh_rejected:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return self._tokens()
        if url == qb.REVOKE_URL:
            self.revoked.append(json.loads(request.content)["token"])
            return httpx.Response(200)
        if "/bill/" in url and request.method == "GET":
            bill_id = url.split("/bill/")[1].split("?")[0]
            if bill_id != "145":
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "Bill": {
                        "Id": "145",
                        "SyncToken": str(self.sync_token),
                        "PrivateNote": self.note,
                        "VendorRef": {"value": "56", "name": "Acme Cloud Services"},
                    }
                },
            )
        if url.split("?")[0].endswith("/bill") and request.method == "POST":
            body = json.loads(request.content)
            if "VendorRef" not in body:  # as the real API does, even for sparse updates
                fault = {"Detail": "Required parameter VendorRef is missing in the request"}
                return httpx.Response(400, json={"Fault": {"Error": [fault]}})
            if "Id" not in body:  # a new bill
                bill = {**body, "Id": str(900 + len(self.created)), "SyncToken": "0"}
                bill["TotalAmt"] = sum(line["Amount"] for line in body["Line"])
                self.created.append(bill)
                return httpx.Response(200, json={"Bill": bill})
            # Only the note may change: nothing else is sent
            assert body["sparse"] is True
            assert set(body) == {"Id", "SyncToken", "sparse", "VendorRef", "PrivateNote"}
            if body["SyncToken"] != str(self.sync_token):
                return httpx.Response(400, json={"Fault": "stale"})
            self.note = body["PrivateNote"]
            self.sync_token += 1
            self.updates += 1
            return httpx.Response(
                200,
                json={
                    "Bill": {
                        "Id": "145",
                        "SyncToken": str(self.sync_token),
                        "PrivateNote": self.note,
                        "MetaData": {"LastUpdatedTime": "2026-10-20T10:00:00-07:00"},
                    }
                },
            )
        if "/reports/" in url:
            self.report_calls += 1
            if self.reports_fail:
                return httpx.Response(500)
            name = url.split("/reports/")[1].split("?")[0]
            return httpx.Response(200, json=REPORTS[name])
        if "/preferences" in url:
            prefs = {"AccountingInfoPrefs": {"BookCloseDate": "2026-08-31"}}
            return httpx.Response(200, json={"Preferences": prefs})
        if "/companyinfo/" in url:
            return httpx.Response(200, json={"CompanyInfo": {"CompanyName": "Acme Holdings Ltd"}})
        if "/query" in url:
            statement = request.url.params["query"]
            entity = statement.split(" FROM ")[1].split(" ")[0]
            if " WHERE DocNumber = " in statement:
                number = statement.split(" WHERE DocNumber = ")[1].strip("'")
                existing = [
                    {"Id": "145", "DocNumber": "INV-2048", "VendorRef": {"value": "56"}},
                    *self.created,
                ]
                found = [b for b in existing if b["DocNumber"] == number]
                return httpx.Response(200, json={"QueryResponse": {"Bill": found}})
            rows = {
                "Vendor": self.vendors,
                "PurchaseOrder": [
                    {
                        "Id": "301",
                        "DocNumber": "PO-77",
                        "VendorRef": {"value": "56", "name": "Acme Cloud Services"},
                        "TotalAmt": 12500.0,
                        "POStatus": "Open",
                        "TxnDate": "2026-09-30",
                    }
                ],
                "Bill": [
                    {
                        "Id": "145",
                        "DocNumber": "INV-2048",
                        "VendorRef": {"value": "56", "name": "Acme Cloud Services"},
                        "TotalAmt": 12500.0,
                        "TxnTaxDetail": {"TotalTax": 500.0},
                        "TxnDate": "2026-10-01",
                        "LinkedTxn": [{"TxnId": "301", "TxnType": "PurchaseOrder"}],
                        "Line": [
                            {
                                "AccountBasedExpenseLineDetail": {
                                    "AccountRef": {"value": "7", "name": "6100 Cloud Hosting"}
                                }
                            }
                        ],
                    }
                ],
                "Account": [
                    {
                        "Id": "7",
                        "AcctNum": "6100",
                        "Name": "Cloud Hosting",
                        "AccountType": "Expense",
                    },
                    {
                        "Id": "3",
                        "Name": "Operating Account",
                        "AccountType": "Bank",
                        "CurrentBalance": 250000.0,
                    },
                    {
                        "Id": "84",
                        "AcctNum": "1200",
                        "Name": "Accounts Receivable (A/R)",
                        "AccountType": "Accounts Receivable",
                    },
                    {
                        "Id": "33",
                        "AcctNum": "2000",
                        "Name": "Accounts Payable (A/P)",
                        "AccountType": "Accounts Payable",
                    },
                    {"Id": "79", "Name": "Sales", "AccountType": "Income"},
                    {"Id": "80", "Name": "Rent", "AccountType": "Expense"},
                ],
                "Budget": self.budgets,
                **RECEIVABLES_AND_EXPENSES,
            }[entity]
            rows = [*rows, *self.extra.get(entity, [])]
            return httpx.Response(200, json={"QueryResponse": {entity: rows}})
        return httpx.Response(404)


@pytest.fixture
def intuit(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeIntuit]:
    fake = FakeIntuit()
    monkeypatch.setattr(qb, "transport", httpx.MockTransport(fake.handler))
    yield fake


@pytest.fixture
async def admin(make_user: MakeUser) -> User:
    return await make_user("admin@example.com", UserRole.FINANCE_ADMIN)


async def assign(db: AsyncSession, user: User, capacity: AgentCapacity) -> None:
    agent = await db.scalar(select(Agent).where(Agent.key == "ap_invoice"))
    assert agent is not None
    db.add(AgentAssignment(user_id=user.id, agent_id=agent.id, capacity=capacity))
    await db.commit()


@pytest.fixture
async def analyst(make_user: MakeUser, db: AsyncSession) -> User:
    user = await make_user("ap.analyst@example.com")
    await assign(db, user, AgentCapacity.PREPARER)
    return user


@pytest.fixture
async def adm(admin: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(admin)


@pytest.fixture
async def me(analyst: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(analyst)


def state_of(url: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["redirect_uri"] == [
        "http://localhost:8081/api/v1/data-sources/quickbooks/callback"
    ]
    assert query["client_id"] == [APP["client_id"]]
    return query["state"][0]


async def start(client: AsyncClient, source_id: str | None = None) -> Any:
    """Connect with the user's own app, or re-authorize an existing source."""
    if source_id is None:
        r = await client.post(f"{SOURCES}/quickbooks", json=APP)
    else:
        r = await client.post(f"{SOURCES}/{source_id}/authorize")
    assert r.status_code == 200, r.text
    return r.json()


async def connect(client: AsyncClient, source_id: str | None = None, realm: str = REALM) -> Any:
    """Run the OAuth round trip the browser would do; returns the callback redirect."""
    state = state_of((await start(client, source_id))["url"])
    callback = await client.get(
        f"{SOURCES}/quickbooks/callback",
        params={"state": state, "code": "good-code", "realmId": realm},
    )
    assert callback.status_code == 303
    return urllib.parse.parse_qs(urllib.parse.urlparse(callback.headers["location"]).query)


# --- the user's own Intuit app -------------------------------------------------------------


async def test_each_user_brings_their_own_app_and_the_secret_stays_hidden(
    me: AsyncClient, db: AsyncSession
) -> None:
    uri = (await me.get(f"{SOURCES}/quickbooks/redirect-uri")).json()["redirect_uri"]
    assert uri == "http://localhost:8081/api/v1/data-sources/quickbooks/callback"

    missing = await me.post(f"{SOURCES}/quickbooks", json={**APP, "client_secret": ""})
    assert missing.status_code == 422

    started = await start(me)
    assert started["source"]["client_id"] == "ABclient"
    assert started["source"]["status"] == "pending_auth"
    assert "super-secret" not in json.dumps(started)
    row = await db.get(DataSource, started["source"]["id"])
    assert row is not None and row.client_secret_enc is not None
    assert crypto.decrypt(row.client_secret_enc) == "super-secret"

    # Retrying (or double-clicking Connect) reuses the unfinished connection
    again = await start(me)
    assert again["source"]["id"] == started["source"]["id"]
    assert len((await me.get(SOURCES)).json()) == 1


async def test_changing_the_app_requires_reauthorization(
    me: AsyncClient, intuit: FakeIntuit, db: AsyncSession
) -> None:
    source_id = (await connect(me))["source"][0]
    same = await me.put(
        f"{SOURCES}/{source_id}/app", json={"client_id": "ABclient", "environment": "sandbox"}
    )
    assert same.json()["status"] == "connected"  # nothing changed

    r = await me.put(
        f"{SOURCES}/{source_id}/app",
        json={"client_id": "ABother", "client_secret": "other-secret", "environment": "sandbox"},
    )
    assert r.json()["status"] == "needs_reauth"
    row = await db.get(DataSource, source_id)
    assert row is not None and row.credentials_enc is None  # old tokens dropped
    assert (await me.post(f"{SOURCES}/{source_id}/sync")).status_code == 409


async def test_two_users_can_connect_the_same_company_separately(
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
) -> None:
    other = await signed_in_client(await make_user("other@example.com"))
    first = (await connect(me))["source"][0]
    second = (await connect(other))["source"][0]
    assert first != second
    assert [s["id"] for s in (await me.get(SOURCES)).json()] == [first]
    assert [s["id"] for s in (await other.get(SOURCES)).json()] == [second]


# --- OAuth + sync -------------------------------------------------------------------------


async def test_user_connects_own_quickbooks_and_it_syncs(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit, db: AsyncSession
) -> None:
    result = await connect(me)
    assert result["quickbooks"] == ["connected"]

    [source] = (await me.get(SOURCES)).json()
    assert source["id"] == result["source"][0]
    assert source["status"] == "connected"
    assert source["name"] == "Acme Holdings Ltd"
    assert source["record_counts"] == {
        "vendor": 2,
        "purchase_order": 1,
        "bill": 1,
        "account": 6,
        "customer": 2,
        "invoice": 3,
        "payment": 2,
        "expense": 2,
        # month-end history, fetched by the background job (run inline in tests)
        "account_balance": 3 * 24,
        "subledger_total": 2 * 24,
        # East, West and company: actual P&L and budget, every month
        "period_result": 3 * 24 + 3 * 24,
    }
    assert source["history_status"] == "ready"
    assert source["books_closed_through"] == "2026-08-31"
    # trial balance, AR and AP aging, and P&L, per month
    assert intuit.report_calls == 4 * 24
    assert "credentials" not in json.dumps(source)

    bills = (await me.get(f"{SOURCES}/{source['id']}/records", params={"type": "bill"})).json()
    assert bills[0]["data"]["po_number"] == "PO-77"  # linked PO resolved to its number
    assert bills[0]["data"]["account"] == "6100 Cloud Hosting"

    def records(record_type: str) -> Any:
        return me.get(f"{SOURCES}/{source['id']}/records", params={"type": record_type})

    invoices = {r["reference"]: r["data"] for r in (await records("invoice")).json()}
    assert invoices["INV-8000"]["paid_date"] == "2026-08-20"  # its payment's date
    assert invoices["INV-8021"]["paid_date"] is None
    assert invoices["INV-8021"]["balance"] == "1000.00"
    payments = {r["reference"]: r["data"] for r in (await records("payment")).json()}
    assert payments["CHK-100"]["invoice_number"] == "INV-8000"  # linked invoice id resolved
    assert payments["CHK-100"]["applied_amount"] == "500.00"
    assert payments["WIRE-2901"]["invoice_number"] is None
    assert payments["WIRE-2901"]["memo"] == "Short paid INV-8021: damaged pallet"
    expenses = {r["reference"]: r["data"] for r in (await records("expense")).json()}
    assert expenses["501"]["has_receipt"] is True and expenses["502"]["has_receipt"] is False
    assert expenses["501"]["account"] == "Lodging"
    assert expenses["501"]["vendor_name"] == "Northbridge Hotel"

    row = await db.get(DataSource, source["id"])
    assert row is not None and row.credentials_enc is not None
    assert "rt-1" not in row.credentials_enc  # encrypted at rest
    assert crypto.decrypt_json(row.credentials_enc)["refresh_token"] == "rt-1"


async def test_callback_state_is_signed_and_single_use(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit
) -> None:
    state = state_of((await start(me))["url"])
    params = {"state": state, "code": "good-code", "realmId": REALM}

    assert (await me.get(f"{SOURCES}/quickbooks/callback", params=params)).status_code == 303
    replay = await me.get(f"{SOURCES}/quickbooks/callback", params=params)
    assert "quickbooks=error" in replay.headers["location"]

    forged = await me.get(
        f"{SOURCES}/quickbooks/callback", params={**params, "state": "not-a-token"}
    )
    assert "quickbooks=error" in forged.headers["location"]


async def test_cancelled_authorization_is_reported(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit
) -> None:
    state = state_of((await start(me))["url"])
    callback = await me.get(
        f"{SOURCES}/quickbooks/callback", params={"state": state, "error": "access_denied"}
    )
    location = urllib.parse.parse_qs(urllib.parse.urlparse(callback.headers["location"]).query)
    assert location["quickbooks"] == ["error"]
    assert "cancelled" in location["message"][0]
    [source] = (await me.get(SOURCES)).json()
    assert source["status"] == "pending_auth"


async def test_expired_access_is_refreshed_and_rotation_kept(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit, db: AsyncSession
) -> None:
    source_id = (await connect(me))["source"][0]
    row = await db.get(DataSource, source_id)
    assert row is not None and row.credentials_enc is not None
    tokens = crypto.decrypt_json(row.credentials_enc)
    tokens["access_expires_at"] = (utcnow() - timedelta(minutes=5)).isoformat()
    row.credentials_enc = crypto.encrypt_json(tokens)
    await db.commit()

    r = await me.post(f"{SOURCES}/{source_id}/sync")
    assert r.status_code == 200, r.text
    await db.refresh(row)
    assert row.credentials_enc is not None
    assert crypto.decrypt_json(row.credentials_enc)["refresh_token"] == "rt-2"


async def test_revoked_access_needs_reauthorization_of_the_same_company(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit, db: AsyncSession
) -> None:
    source_id = (await connect(me))["source"][0]
    row = await db.get(DataSource, source_id)
    assert row is not None and row.credentials_enc is not None
    tokens = crypto.decrypt_json(row.credentials_enc)
    tokens["access_expires_at"] = (utcnow() - timedelta(minutes=5)).isoformat()
    row.credentials_enc = crypto.encrypt_json(tokens)
    await db.commit()
    intuit.refresh_rejected = True

    r = await me.post(f"{SOURCES}/{source_id}/sync")
    assert r.status_code == 409
    assert "Re-authorize" in r.json()["detail"]["message"]
    assert (await me.get(f"{SOURCES}/{source_id}")).json()["status"] == "needs_reauth"

    other = await connect(me, source_id, realm="999")
    assert "different company" in other["message"][0]

    intuit.refresh_rejected = False
    again = await connect(me, source_id)
    assert again["quickbooks"] == ["connected"]
    assert (await me.get(f"{SOURCES}/{source_id}")).json()["status"] == "connected"


async def test_disconnect_revokes_access(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit
) -> None:
    source_id = (await connect(me))["source"][0]
    assert (await me.delete(f"{SOURCES}/{source_id}")).status_code == 204
    assert intuit.revoked == ["rt-1"]
    assert (await me.get(SOURCES)).json() == []


# --- privacy ------------------------------------------------------------------------------


async def test_sources_are_private_to_their_owner(
    adm: AsyncClient,
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
) -> None:
    source_id = (await connect(me))["source"][0]
    other = await signed_in_client(await make_user("other@example.com"))

    assert (await other.get(SOURCES)).json() == []
    assert (await other.get(f"{SOURCES}/{source_id}")).status_code == 404
    r = await other.get(f"{SOURCES}/{source_id}/records", params={"type": "bill"})
    assert r.status_code == 404
    assert (await other.post(f"{SOURCES}/{source_id}/sync")).status_code == 404
    assert (await other.delete(f"{SOURCES}/{source_id}")).status_code == 404
    assert (await other.post(f"{SOURCES}/{source_id}/authorize")).status_code == 404
    app = {"client_id": "x", "environment": "sandbox"}
    assert (await other.put(f"{SOURCES}/{source_id}/app", json=app)).status_code == 404

    # The admin sees status per user, never credentials or records
    assert (await adm.get(f"{SOURCES}/{source_id}")).status_code == 404
    [listed] = (await adm.get("/api/v1/admin/data-sources")).json()
    assert listed["owner"]["email"] == "ap.analyst@example.com"
    assert listed["status"] == "connected"
    assert (await me.get("/api/v1/admin/data-sources")).status_code == 403


# --- uploads ------------------------------------------------------------------------------

BILLS_CSV = (
    b"Invoice No,Supplier,Amount,Tax,Invoice Date,PO Number\n"
    b'INV-1,Acme Cloud Services,"1,250.00",50,2026-10-01,PO-1\n'
    b"INV-2,Globex,300.00,,05/10/2026,\n"
    b"INV-3,,abc,,,\n"
)


async def upload(client: AsyncClient, path: str, data: bytes, **form: Any) -> httpx.Response:
    return await client.post(
        f"{SOURCES}/uploads{path}", files={"file": ("bills.csv", data)}, data=form
    )


async def test_upload_preview_suggests_a_mapping(me: AsyncClient) -> None:
    r = await upload(me, "/preview", BILLS_CSV, record_type="bill")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mapping"] == {
        "external_id": None,
        "doc_number": "Invoice No",
        "vendor_name": "Supplier",
        "total": "Amount",
        "tax_total": "Tax",
        "bill_date": "Invoice Date",
        "due_date": None,
        "po_number": "PO Number",
        "account": None,
        "balance": None,
    }
    assert (body["row_count"], body["valid_count"], body["error_count"]) == (3, 2, 1)
    assert body["errors"][0].startswith("Row 4: total: 'abc' is not an amount")


async def test_upload_maps_a_bank_payments_file(me: AsyncClient) -> None:
    payments = (
        b"Date,Customer,Reference,Amount,Invoice No,Remittance\n"
        b"15/10/2026,Harbor Distribution,WIRE-2901,900.00,,Short paid INV-8021\n"
    )
    body = (await upload(me, "/preview", payments, record_type="payment")).json()
    assert body["mapping"] == {
        "external_id": None,
        "reference_number": "Reference",
        "customer_name": "Customer",
        "total": "Amount",
        "payment_date": "Date",
        "invoice_number": "Invoice No",
        "applied_amount": None,
        "unapplied_amount": None,
        "memo": "Remittance",
    }
    assert (body["valid_count"], body["error_count"]) == (1, 0)


async def test_upload_rejects_bad_rows_unless_skipped(me: AsyncClient) -> None:
    mapping = (await upload(me, "/preview", BILLS_CSV, record_type="bill")).json()["mapping"]
    form = {"record_type": "bill", "mapping": json.dumps(mapping)}

    rejected = await upload(me, "", BILLS_CSV, **form)
    assert rejected.status_code == 422
    assert "1 row(s) have problems" in rejected.json()["detail"]["message"]

    r = await upload(me, "", BILLS_CSV, **form, skip_invalid="true", name="October bills")
    assert r.status_code == 201, r.text
    assert (r.json()["imported"], r.json()["skipped"]) == (2, 1)
    source = r.json()["source"]
    assert (source["kind"], source["status"], source["name"]) == (
        "upload",
        "ready",
        "October bills",
    )

    records = (await me.get(f"{SOURCES}/{source['id']}/records", params={"type": "bill"})).json()
    by_ref = {rec["reference"]: rec for rec in records}
    assert by_ref["INV-1"]["amount"] == "1250.00"
    assert by_ref["INV-2"]["txn_date"] == "2026-10-05"  # DD/MM/YYYY

    again = await upload(me, "", BILLS_CSV, **form, skip_invalid="true")
    assert "already uploaded" in again.json()["detail"]["message"]


# --- agents use the user's data -----------------------------------------------------------


async def test_run_prefilled_from_quickbooks_with_snapshot_for_reviewer(
    adm: AsyncClient,
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    db: AsyncSession,
    fake_llm: FakeLLM,
) -> None:
    source_id = (await connect(me))["source"][0]
    run = (await me.post(RUNS)).json()

    r = await me.put(
        f"{RUNS}/{run['id']}/source", json={"source_id": source_id, "record_id": "145"}
    )
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["input"]["supplier"] == "Acme Cloud Services"
    assert run["input"]["invoice_number"] == "INV-2048"
    assert run["input"]["po_authorized_amount"] == "12500.00"  # from the linked PO
    assert run["input"]["proposed_gl_account"] == "6100 Cloud Hosting"
    assert run["source"]["records"]["purchase_order"]["po_number"] == "PO-77"

    # Received amount isn't in QuickBooks: the preparer completes it
    values = {**run["input"], "received_amount": "12500.00"}
    await me.put(f"{RUNS}/{run['id']}/input", json={"values": values})
    run = (await me.post(f"{RUNS}/{run['id']}/analyze")).json()
    flags = {f["code"]: f["severity"] for f in run["flags"]}
    assert flags["VENDOR_IN_MASTER"] == "pass"
    run = (await me.post(f"{RUNS}/{run['id']}/submit")).json()

    # The approving admin can't open the user's data source, only the run's snapshot
    seen = (await adm.get(f"{RUNS}/{run['id']}")).json()
    assert (await adm.get(f"{SOURCES}/{source_id}")).status_code == 404
    assert seen["source"]["records"]["bill"]["doc_number"] == "INV-2048"

    # Deleting the source keeps what the reviewer approves against
    assert (await me.delete(f"{SOURCES}/{source_id}")).status_code == 204
    kept = (await me.get(f"{RUNS}/{run['id']}")).json()
    assert kept["source"]["source_id"] is None
    assert kept["source"]["source_name"] == "Acme Holdings Ltd"
    assert kept["result_hash"] == run["result_hash"]


async def test_vendor_master_flags_unknown_and_inactive_suppliers(
    adm: AsyncClient, me: AsyncClient, intuit: FakeIntuit, fake_llm: FakeLLM
) -> None:
    await connect(me)
    run = (await me.post(RUNS)).json()
    base = {
        "invoice_number": "X-1",
        "invoice_total": "10.00",
        "po_authorized_amount": "10.00",
        "received_amount": "10.00",
    }
    for supplier, code in (
        ("Unknown Co", "VENDOR_NOT_IN_MASTER"),
        ("Old Supplier", "VENDOR_INACTIVE"),
    ):
        await me.put(f"{RUNS}/{run['id']}/input", json={"values": {**base, "supplier": supplier}})
        analyzed = (await me.post(f"{RUNS}/{run['id']}/analyze")).json()
        assert code in {f["code"] for f in analyzed["flags"]}


async def test_cannot_prefill_from_someone_elses_source(
    adm: AsyncClient,
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    db: AsyncSession,
) -> None:
    source_id = (await connect(me))["source"][0]
    other_user = await make_user("other@example.com")
    await assign(db, other_user, AgentCapacity.PREPARER)
    other = await signed_in_client(other_user)
    run = (await other.post(RUNS)).json()
    r = await other.put(
        f"{RUNS}/{run['id']}/source", json={"source_id": source_id, "record_id": "145"}
    )
    assert r.status_code == 404
    assert (await db.get(DataSource, source_id)).status == SourceStatus.CONNECTED  # type: ignore[union-attr]


# --- write-back after approval ----------------------------------------------------------


async def approved_from_quickbooks(client: AsyncClient, admin: AsyncClient) -> dict[str, Any]:
    source_id = (await connect(client))["source"][0]
    run = (await client.post(RUNS)).json()
    run = (
        await client.put(
            f"{RUNS}/{run['id']}/source", json={"source_id": source_id, "record_id": "145"}
        )
    ).json()
    values = {**run["input"], "received_amount": "12500.00"}
    await client.put(f"{RUNS}/{run['id']}/input", json={"values": values})
    await client.post(f"{RUNS}/{run['id']}/analyze")
    await client.post(f"{RUNS}/{run['id']}/submit")
    r = await admin.post(
        f"{RUNS}/{run['id']}/reviews", json={"decision": "approved", "comment": "Checked it"}
    )
    assert r.json()["status"] == "approved", r.text
    result: dict[str, Any] = r.json()
    return result


async def test_preparer_writes_the_approval_back_once(
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    run = await approved_from_quickbooks(me, admin)
    assert run["permissions"]["can_write_back"] is False  # the admin's view
    mine = (await me.get(f"{RUNS}/{run['id']}")).json()
    assert mine["permissions"]["can_write_back"] is True

    assert (await admin.post(f"{RUNS}/{run['id']}/write-back")).status_code == 403
    done = (await me.post(f"{RUNS}/{run['id']}/write-back")).json()
    [action] = done["actions"]
    assert action["status"] == "succeeded"
    assert action["receipt"]["bill_id"] == "145"
    assert action["receipt"]["sync_token"] == "4"
    assert intuit.note.startswith("Entered by AP\n[FinanceACC] ")
    assert f"{run['reference']} approved by Admin" in intuit.note
    assert done["permissions"]["can_write_back"] is False

    again = await me.post(f"{RUNS}/{run['id']}/write-back")
    assert again.status_code == 403 and intuit.updates == 1

    summaries = {e["summary"] for e in (await admin.get("/api/v1/audit-events")).json()["items"]}
    assert f"Noted the approval of {run['reference']} on QuickBooks bill 145" in summaries


async def test_write_back_is_not_offered_before_approval_or_without_quickbooks(
    me: AsyncClient,
    intuit: FakeIntuit,
    fake_llm: FakeLLM,
) -> None:
    run = (await me.post(RUNS)).json()
    assert run["permissions"]["can_write_back"] is False
    r = await me.post(f"{RUNS}/{run['id']}/write-back")
    assert r.status_code == 403
    assert "approved" in r.json()["detail"]["message"]


async def test_a_note_already_there_is_not_written_twice(
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    run = await approved_from_quickbooks(me, admin)
    intuit.note = f"[FinanceACC] {run['reference']} approved earlier"
    done = (await me.post(f"{RUNS}/{run['id']}/write-back")).json()
    assert done["actions"][0]["receipt"]["already_present"] is True
    assert intuit.updates == 0


async def approved_by_hand(
    client: AsyncClient,
    admin: AsyncClient,
    invoice_number: str = "INV-3001",
    supplier: str = "acme cloud services",  # matched to the QuickBooks vendor ignoring case
) -> dict[str, Any]:
    run = (await client.post(RUNS)).json()
    values = {
        "supplier": supplier,
        "invoice_number": invoice_number,
        "invoice_total": "980.50",
        "po_authorized_amount": "980.50",
        "received_amount": "980.50",
        "tax_total": None,
        "proposed_gl_account": None,
    }
    await client.put(f"{RUNS}/{run['id']}/input", json={"values": values})
    await client.post(f"{RUNS}/{run['id']}/analyze")
    await client.post(f"{RUNS}/{run['id']}/submit")
    r = await admin.post(
        f"{RUNS}/{run['id']}/reviews", json={"decision": "approved", "comment": "Checked it"}
    )
    assert r.json()["status"] == "approved", r.text
    result: dict[str, Any] = r.json()
    return result


async def test_an_invoice_entered_by_hand_becomes_a_quickbooks_bill_once(
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    run = await approved_by_hand(me, admin)
    mine = (await me.get(f"{RUNS}/{run['id']}")).json()["permissions"]
    assert mine["can_write_back"] is False and mine["write_back"] == "create_bill"
    assert "Connect QuickBooks" in mine["write_back_blocked_reason"]
    assert mine["bill"] == {
        "vendor": run["input"]["supplier"],
        "doc_number": "INV-3001",
        "amount": "980.50",
        "account_hint": None,
    }

    source_id = (await connect(me))["source"][0]
    mine = (await me.get(f"{RUNS}/{run['id']}")).json()["permissions"]
    assert mine["can_write_back"] is True and mine["write_back_blocked_reason"] is None
    url = f"{RUNS}/{run['id']}/write-back"
    assert (await me.post(url)).status_code == 403  # which company and account?
    r = await me.post(url, json={"source_id": source_id, "account_id": "999"})
    assert r.status_code == 404  # not a synced account

    done = (await me.post(url, json={"source_id": source_id, "account_id": "7"})).json()
    [action] = done["actions"]
    assert action["status"] == "succeeded", action
    assert action["label"] == "Bill created in QuickBooks"
    assert action["receipt"]["bill_id"] == "900" and action["receipt"]["already_present"] is False
    assert action["receipt"]["vendor"] == "Acme Cloud Services"
    assert action["receipt"]["account"] == "6100 Cloud Hosting"
    [bill] = intuit.created
    assert bill["VendorRef"] == {"value": "56"} and bill["DocNumber"] == "INV-3001"
    assert bill["TotalAmt"] == 980.5
    assert bill["Line"][0]["AccountBasedExpenseLineDetail"]["AccountRef"] == {"value": "7"}
    assert bill["PrivateNote"].startswith(f"[FinanceACC] {run['reference']} approved by Admin")
    assert done["permissions"]["can_write_back"] is False
    again = await me.post(url, json={"source_id": source_id, "account_id": "7"})
    assert again.status_code == 403 and len(intuit.created) == 1

    summaries = {e["summary"] for e in (await admin.get("/api/v1/audit-events")).json()["items"]}
    assert f"Created QuickBooks bill 900 for {run['reference']}" in summaries


async def test_an_existing_bill_with_that_number_is_not_duplicated(
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
) -> None:
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    source_id = (await connect(me))["source"][0]
    run = await approved_by_hand(me, admin, invoice_number="INV-2048")
    done = (
        await me.post(
            f"{RUNS}/{run['id']}/write-back", json={"source_id": source_id, "account_id": "7"}
        )
    ).json()
    receipt = done["actions"][0]["receipt"]
    assert receipt["bill_id"] == "145" and receipt["already_present"] is True
    assert intuit.created == []


async def test_bill_needs_a_vendor_known_to_quickbooks_and_your_own_connection(
    me: AsyncClient,
    intuit: FakeIntuit,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    admin = await signed_in_client(await make_user("admin@example.com", UserRole.FINANCE_ADMIN))
    source_id = (await connect(me))["source"][0]
    body = {"source_id": source_id, "account_id": "7"}
    unknown = await approved_by_hand(me, admin, supplier="Nobody Ltd")
    r = await me.post(f"{RUNS}/{unknown['id']}/write-back", json=body)
    assert r.status_code == 409 and "No vendor named" in r.json()["detail"]["message"]

    other_user = await make_user("other@example.com")
    await assign(db, other_user, AgentCapacity.PREPARER)
    other = await signed_in_client(other_user)
    await connect(other)
    theirs = await approved_by_hand(other, admin, "INV-5")
    r = await other.post(f"{RUNS}/{theirs['id']}/write-back", json=body)
    assert r.status_code == 404  # someone else's connection
    assert intuit.created == []
