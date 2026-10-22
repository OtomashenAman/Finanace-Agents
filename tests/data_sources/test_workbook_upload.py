"""Workbook uploads: one XLSX, one sheet per record type, imported as one data source."""

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.models import AgentCapacity
from src.app.auth.models import User
from src.app.data_sources.records import RecordType
from src.app.data_sources.uploads import sheet_record_type
from tests.agent_catalog.test_runs_api import assign
from tests.conftest import ClientFactory, FakeLLM, MakeUser
from tests.data_sources.test_api import SOURCES

SAMPLE = Path("docs/sample-uploads/all-agents.xlsx")
SAMPLE_XLSX = SAMPLE.read_bytes()


@pytest.fixture
async def preparer(make_user: MakeUser) -> User:
    return await make_user("books@example.com")


@pytest.fixture
async def me(preparer: User, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(preparer)


def workbook(**sheets: list[list[Any]]) -> bytes:
    """An XLSX with these sheets (name -> rows, header first); "_" in a name is a space."""
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name.replace("_", " "))
        for row in rows:
            sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


BILLS = [["Bill No", "Vendor", "Total"], ["B-1", "Acme", 100.0], ["B-2", "Globex", 250.5]]
CUSTOMERS = [["Name", "Email"], ["Harbor Distribution", "ap@harbor.example"]]


async def send(
    client: AsyncClient,
    data: bytes,
    *,
    preview: bool = False,
    filename: str = "book.xlsx",
    sheets: dict[str, Any] | None = None,
    **form: Any,
) -> httpx.Response:
    if sheets is not None:
        form["sheets"] = json.dumps(sheets)
    path = f"{SOURCES}/uploads/workbook{'/preview' if preview else ''}"
    return await client.post(path, files={"file": (filename, data)}, data=form)


def test_sheet_names_give_the_record_type() -> None:
    assert sheet_record_type("Bills") == RecordType.BILL
    assert sheet_record_type("Customer invoices") == RecordType.INVOICE
    assert sheet_record_type("P&L") == RecordType.PERIOD_RESULT
    assert sheet_record_type("Trial balance") == RecordType.ACCOUNT_BALANCE
    # The upload type's own label works too
    assert sheet_record_type("AR / AP subledger totals by month") == RecordType.SUBLEDGER_TOTAL
    assert sheet_record_type("Notes") is None


async def test_sample_workbook_previews_every_type(me: AsyncClient) -> None:
    r = await send(me, SAMPLE_XLSX, preview=True, filename=SAMPLE.name)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["errors"] == []
    assert {s["record_type"] for s in body["sheets"]} == {t.value for t in RecordType}
    for sheet in body["sheets"]:
        preview = sheet["preview"]
        assert preview["error_count"] == 0, (sheet["sheet"], preview["errors"])
        assert preview["valid_count"] == preview["row_count"] > 0


async def test_unknown_and_empty_sheets_are_skipped(me: AsyncClient) -> None:
    data = workbook(Bills=BILLS, Notes=[["Prepared by"], ["Finance"]], Empty=[])
    body = (await send(me, data, preview=True)).json()

    sheets = {s["sheet"]: s for s in body["sheets"]}
    assert sheets["Bills"]["preview"]["valid_count"] == 2
    assert sheets["Notes"]["record_type"] is None
    assert sheets["Notes"]["note"] == "Sheet name isn't a known type: pick one or skip it"
    assert sheets["Empty"]["note"] == "No header row and data rows: skipped"
    assert (sheets["Empty"]["empty"], sheets["Notes"]["empty"]) == (True, False)
    assert body["errors"] == []


async def test_a_type_and_mapping_can_be_chosen_per_sheet(me: AsyncClient) -> None:
    data = workbook(Sheet1=[["Ref", "Who", "Amt"], ["B-9", "Acme", 40.0]], Customers=CUSTOMERS)
    choices = {
        "Sheet1": {
            "record_type": "bill",
            "mapping": {"doc_number": "Ref", "vendor_name": "Who", "total": "Amt"},
        },
        "Customers": {"record_type": None},  # skip it
    }
    body = (await send(me, data, preview=True, sheets=choices)).json()

    sheets = {s["sheet"]: s for s in body["sheets"]}
    assert sheets["Sheet1"]["record_type"] == "bill"
    assert sheets["Sheet1"]["preview"]["valid_count"] == 1
    assert (sheets["Customers"]["record_type"], sheets["Customers"]["note"]) == (None, "Skipped")


async def test_two_sheets_of_one_type_are_an_error(me: AsyncClient) -> None:
    data = workbook(Bills=BILLS, Supplier_invoices=BILLS)
    body = (await send(me, data, preview=True)).json()
    assert body["errors"] == [
        "Sheets 'Bills' and 'Supplier invoices' are both Bills (supplier invoices): keep one, "
        "or skip one."
    ]

    r = await send(me, data)
    assert r.status_code == 422
    assert "are both Bills" in r.json()["detail"]["message"]


async def test_nothing_to_import(me: AsyncClient) -> None:
    body = (await send(me, workbook(Notes=[["a"], ["b"]]), preview=True)).json()
    assert body["errors"] == [
        "No sheet to import: name the sheets after a type (e.g. Bills) or pick one."
    ]


async def test_only_xlsx_and_only_known_sheets(me: AsyncClient) -> None:
    r = await send(me, b"Bill No,Vendor,Total\nB-1,Acme,1\n", preview=True, filename="bills.csv")
    assert r.status_code == 422
    assert r.json()["detail"]["message"] == "Upload an .xlsx file with one sheet per type."

    r = await send(me, workbook(Bills=BILLS), preview=True, sheets={"Nope": {"record_type": None}})
    assert r.json()["detail"]["message"] == "Sheet(s) not in the file: Nope."


async def test_import_creates_one_source_with_every_sheet(me: AsyncClient) -> None:
    r = await send(me, SAMPLE_XLSX, filename=SAMPLE.name, name="Sample books")
    assert r.status_code == 201, r.text
    body = r.json()
    source = body["source"]

    assert (source["kind"], source["name"], source["filename"]) == (
        "upload",
        "Sample books",
        "all-agents.xlsx",
    )
    assert source["record_counts"] == {
        "vendor": 3,
        "bill": 3,
        "purchase_order": 1,
        "account": 5,
        "customer": 3,
        "invoice": 4,
        "payment": 2,
        "expense": 2,
        "account_balance": 3,
        "subledger_total": 2,
        "period_result": 9,
    }
    assert (body["imported"], body["skipped"]) == (37, 0)
    assert [s["id"] for s in (await me.get(SOURCES)).json()] == [source["id"]]

    # Excel numbers and dates are read like the CSV text
    bills = (await me.get(f"{SOURCES}/{source['id']}/records", params={"type": "bill"})).json()
    rent = next(b for b in bills if b["reference"] == "RENT-10")
    assert (rent["amount"], rent["txn_date"]) == ("5000.00", "2026-10-01")

    again = await send(me, SAMPLE_XLSX, filename=SAMPLE.name)
    assert "already uploaded" in again.json()["detail"]["message"]


async def test_a_bad_row_stops_the_whole_workbook_unless_skipped(me: AsyncClient) -> None:
    bad_bills = [*BILLS, ["B-3", "Initech", "abc"]]
    data = workbook(Bills=bad_bills, Customers=CUSTOMERS)

    r = await send(me, data)
    assert r.status_code == 422
    assert r.json()["detail"]["message"].startswith("Sheet 'Bills': 1 row(s) have problems.")
    assert (await me.get(SOURCES)).json() == []

    r = await send(me, data, skip_invalid="true")
    assert r.status_code == 201, r.text
    assert (r.json()["imported"], r.json()["skipped"]) == (3, 1)
    assert r.json()["source"]["record_counts"] == {"bill": 2, "customer": 1}


async def test_agents_prefill_from_the_workbook(
    me: AsyncClient, preparer: User, db: AsyncSession, fake_llm: FakeLLM, synced_agents: None
) -> None:
    for key in ("treasury_cash", "revenue_recognition"):
        await assign(db, preparer, AgentCapacity.PREPARER, key=key)
    source_id = (await send(me, SAMPLE_XLSX, filename=SAMPLE.name)).json()["source"]["id"]

    # Treasury adds up three types (bank accounts, invoices, bills) from the one source
    runs = "/api/v1/agents/treasury_cash/runs"
    run = (await me.post(runs)).json()
    r = await me.post(
        f"{runs}/{run['id']}/prefill",
        json={"source_id": source_id, "params": {"forecast_horizon_days": 30}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["input"]["opening_cash"] == "250000.00"

    invoices = (await me.get(f"{SOURCES}/{source_id}/records", params={"type": "invoice"})).json()
    contract = next(i for i in invoices if i["reference"] == "CTR-2026-091")
    runs = "/api/v1/agents/revenue_recognition/runs"
    run = (await me.post(runs)).json()
    r = await me.put(
        f"{runs}/{run['id']}/source",
        json={"source_id": source_id, "record_id": contract["external_id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["input"]["service_term_months"] == 12
    assert r.json()["input"]["performance_obligations"] == "Hosting: 90000.00; Support: 30000.00"
