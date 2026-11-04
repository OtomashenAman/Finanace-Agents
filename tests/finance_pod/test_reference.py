import io

from httpx import AsyncClient
from openpyxl import load_workbook

from src.app.auth.models import UserRole
from tests.conftest import ClientFactory, MakeUser
from tests.finance_pod.conftest import SHEETS, upload, workbook


async def test_only_finance_admins_use_the_finance_pod(
    make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    user = await signed_in_client(await make_user("someone@gia.example", UserRole.USER))
    assert (await user.get("/api/v1/finance-pod/overview")).status_code == 403
    assert (await user.get("/api/v1/finance-pod/requests")).status_code == 403


async def test_the_template_has_every_sheet_and_loads_back(fpod: AsyncClient) -> None:
    r = await fpod.get("/api/v1/finance-pod/reference/template")
    assert r.status_code == 200
    book = load_workbook(io.BytesIO(r.content))
    assert book.sheetnames == [
        "Cost centres",
        "Labs",
        "Projects",
        "Grants",
        "Budgets",
        "Catalogue",
        "Vendors",
        "Authority matrix",
    ]

    loaded = await upload(fpod, r.content)
    assert loaded.status_code == 200, loaded.text
    assert {s["sheet"]: s["created"] for s in loaded.json()["sheets"]}["budgets"] == 2
    # The example people have no Finance Admin account
    assert any("owner@example.org" in w for w in loaded.json()["warnings"])


async def test_a_workbook_loads_and_reloading_updates_by_code(
    fpod: AsyncClient, reference: None
) -> None:
    ref = (await fpod.get("/api/v1/finance-pod/reference")).json()
    assert [c["code"] for c in ref["cost_centres"]] == ["CC-100", "CC-200"]
    budget = next(b for b in ref["budgets"] if b["cost_centre_code"] == "CC-100")
    assert budget["remaining"] == "65000.00"  # 120000 - 10000 committed - 45000 spent
    assert ref["grants"][0]["unallowable_categories"] == ["alcohol", "entertainment"]

    renamed = {
        "Cost centres": [
            ["Code", "Name", "Active"],
            ["CC-200", "Chemistry & Materials", "no"],
        ]
    }
    r = await upload(fpod, workbook(renamed))
    assert r.json()["sheets"] == [
        {"sheet": "cost_centres", "title": "Cost centres", "created": 0, "updated": 1, "removed": 0}
    ]
    ref = (await fpod.get("/api/v1/finance-pod/reference")).json()
    cc = {c["code"]: c for c in ref["cost_centres"]}
    assert cc["CC-200"] == {
        "code": "CC-200",
        "name": "Chemistry & Materials",
        "owner_email": "chem@gia.example",  # a column not in the file is left alone
        "active": False,
    }
    assert "CC-100" in cc  # rows not in the file stay


async def test_errors_name_sheet_and_row_and_nothing_is_imported(fpod: AsyncClient) -> None:
    bad = {
        "Cost centres": SHEETS["Cost centres"],
        "Labs": [["Code", "Name", "Cost Centre"], ["LAB-X", "Lab X", "CC-999"]],
        "Budgets": [
            ["Fiscal Year", "Cost Centre", "Grant", "Amount"],
            [2026, "CC-100", None, "lots"],
            [2026, None, None, 5],
        ],
    }
    r = await upload(fpod, workbook(bad))
    assert r.status_code == 422
    message = r.json()["detail"]["message"]
    assert "Sheet 'Labs' row 2: cost centre 'CC-999' isn't in the cost centre list" in message
    assert "Sheet 'Budgets' row 2: amount 'lots' is not a number." in message
    assert "Sheet 'Budgets' row 3: give a cost centre or a grant" in message
    ref = (await fpod.get("/api/v1/finance-pod/reference")).json()
    assert ref["cost_centres"] == []


async def test_the_authority_matrix_is_replaced_as_a_whole(
    fpod: AsyncClient, reference: None
) -> None:
    r = await upload(
        fpod,
        workbook(
            {
                "Authority matrix": [
                    ["Scope", "Min Amount", "Approver Email", "Capacity"],
                    ["request", 0, "budget@gia.example", "Budget owner"],
                ]
            }
        ),
    )
    assert r.json()["sheets"][0]["removed"] == 2
    ref = (await fpod.get("/api/v1/finance-pod/reference")).json()
    assert [(t["scope"], t["capacity"]) for t in ref["authority"]] == [("request", "Budget owner")]


async def test_settings_default_and_change(fpod: AsyncClient) -> None:
    r = await fpod.get("/api/v1/finance-pod/settings")
    assert r.json()["purchasing_threshold"] == "10000.00"
    assert r.json()["allow_self_approval"] is False
    r = await fpod.put(
        "/api/v1/finance-pod/settings",
        json={
            "currency": "USD",
            "purchasing_threshold": "5000",
            "min_quotes": 2,
            "allow_self_approval": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["min_quotes"] == 2
    audit = await fpod.get("/api/v1/audit-events", params={"category": "finance_pod"})
    assert any("Finance POD settings" in e["summary"] for e in audit.json()["items"])
