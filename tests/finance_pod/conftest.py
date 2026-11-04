"""Finance POD fixtures: a research institute's coding (test data, not a client's)."""

import io
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import Workbook

from src.app.auth.models import UserRole
from src.app.common.clock import utcnow
from tests.conftest import ClientFactory, MakeUser

TODAY = utcnow().date()
NEXT_MONTH = (TODAY + timedelta(days=30)).isoformat()

SHEETS: dict[str, list[list[Any]]] = {
    "Cost centres": [
        ["Code", "Name", "Owner Email", "Active"],
        ["CC-100", "Biology Department", "budget@gia.example", "yes"],
        ["CC-200", "Chemistry Department", "chem@gia.example", "yes"],
    ],
    "Labs": [
        ["Code", "Name", "Cost Centre"],
        ["LAB-GEN", "Genomics Lab", "CC-100"],
        ["LAB-ORG", "Organic Synthesis Lab", "CC-200"],
    ],
    "Projects": [
        ["Code", "Name", "Cost Centre", "Grant"],
        ["PRJ-7", "Sequencing study", "CC-100", "GR-22"],
    ],
    "Grants": [
        [
            "Code",
            "Name",
            "Sponsor",
            "Cost Centre",
            "Start Date",
            "End Date",
            "Award Amount",
            "Unallowable Categories",
        ],
        [
            "GR-22",
            "Sequencing grant",
            "NSF",
            "CC-100",
            (TODAY - timedelta(days=365)).isoformat(),
            (TODAY + timedelta(days=365)).isoformat(),
            250000,
            "alcohol; entertainment",
        ],
    ],
    "Budgets": [
        ["Fiscal Year", "Cost Centre", "Grant", "Category", "Amount", "Committed", "Spent"],
        [TODAY.year, "CC-100", None, None, 120000, 10000, 45000],
        [TODAY.year, None, "GR-22", "lab supplies", 80000, 0, 12000],
    ],
    "Catalogue": [
        ["Item Code", "Description", "Category", "Unit", "Unit Price", "Vendor", "Contract Ref"],
        [
            "PIP-200",
            "Pipette tips 200ul sterile",
            "lab supplies",
            "box",
            42.50,
            "V-LAB",
            "CT-2026-01",
        ],
        ["GLV-M", "Nitrile gloves medium", "lab supplies", "box", 9.00, "V-LAB", "CT-2026-01"],
    ],
    "Vendors": [
        ["Code", "Name", "Email", "Tax ID", "Status", "Categories"],
        [
            "V-LAB",
            "Lab Supply Co",
            "orders@labsupply.example",
            "12-3456789",
            "approved",
            "lab supplies",
        ],
    ],
    "Authority matrix": [
        ["Scope", "Cost Centre", "Min Amount", "Approver Email", "Capacity"],
        ["request", None, 0, "budget@gia.example", "Budget owner"],
        ["po", None, 50000, "buyer@gia.example", "Buyer"],
    ],
}


def workbook(sheets: dict[str, list[list[Any]]]) -> bytes:
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    for title, rows in sheets.items():
        ws = book.create_sheet(title)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


async def upload(client: AsyncClient, data: bytes) -> Any:
    return await client.post(
        "/api/v1/finance-pod/reference/workbook",
        files={"file": ("reference.xlsx", data, "application/octet-stream")},
    )


@pytest.fixture
async def fpod(make_user: MakeUser, signed_in_client: ClientFactory) -> AsyncClient:
    """The requester: a signed-in Finance Admin."""
    return await signed_in_client(await make_user("buyer@gia.example", UserRole.FINANCE_ADMIN))


@pytest.fixture
async def other_admin(make_user: MakeUser, signed_in_client: ClientFactory) -> AsyncClient:
    return await signed_in_client(await make_user("budget@gia.example", UserRole.FINANCE_ADMIN))


@pytest.fixture
async def reference(fpod: AsyncClient) -> None:
    r = await upload(fpod, workbook(SHEETS))
    assert r.status_code == 200, r.text


def request_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Pipette tips for sequencing run",
        "purpose": "Consumables for the sequencing study's next run",
        "needed_by": NEXT_MONTH,
        "cost_centre_code": "CC-100",
        "lab_code": "LAB-GEN",
        "project_code": "PRJ-7",
        "grant_code": "GR-22",
        "lines": [
            {
                "description": "Pipette tips 200ul sterile",
                "quantity": "10",
                "unit": "box",
                "unit_price": "42.50",
                "category": "lab supplies",
            }
        ],
    }
    body.update(changes)
    return body
