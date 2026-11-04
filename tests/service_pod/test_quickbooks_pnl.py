"""FP&A evidence from QuickBooks Online: the ProfitAndLoss (by month) and ProfitAndLossDetail
reports, read at snapshot time, become GL lines and the transactions behind them."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.data_sources.records import Account, Customer, RecordType
from src.app.entities.models import LegalEntity
from src.app.service_pod.core.snapshots import service as snapshot_service
from src.app.service_pod.core.snapshots.contract import AccountClass, SnapshotDocument
from src.app.service_pod.core.snapshots.importers.quickbooks_pnl import (
    PnlReports,
    build_pnl,
    last_complete_months,
)
from src.app.service_pod.flows.fpa_trend.engine import compute
from src.app.service_pod.flows.fpa_trend.schemas import FpaSelection
from tests.service_pod.test_quickbooks_snapshot import _connection


def _month(start: str, end: str, title: str) -> dict[str, Any]:
    return {
        "ColTitle": title,
        "ColType": "Money",
        "MetaData": [{"Name": "StartDate", "Value": start}, {"Name": "EndDate", "Value": end}],
    }


def _cells(*values: str, account: tuple[str, str] | None = None) -> list[dict[str, str]]:
    first = {"value": account[1], "id": account[0]} if account else {"value": ""}
    return [first, *({"value": v} for v in values)]


BY_MONTH: dict[str, Any] = {
    "Columns": {
        "Column": [
            {"ColTitle": "", "ColType": "Account"},
            _month("2026-08-01", "2026-08-31", "Aug 2026"),
            _month("2026-09-01", "2026-09-30", "Sep 2026"),
            {"ColTitle": "Total", "ColType": "Money"},
        ]
    },
    "Rows": {
        "Row": [
            {
                "group": "Income",
                "Header": {"ColData": _cells("", "", "")},
                "Rows": {
                    "Row": [
                        {
                            "ColData": _cells(
                                "480.00", "540.00", "1020.00", account=("1", "Services")
                            ),
                            "type": "Data",
                        }
                    ]
                },
                "Summary": {"ColData": _cells("480.00", "540.00", "1020.00")},
                "type": "Section",
            },
            {
                "group": "COGS",
                "Header": {"ColData": _cells("", "", "")},
                "Rows": {
                    "Row": [
                        {
                            "ColData": _cells(
                                "288.00", "318.00", "606.00", account=("2", "Subcontractors")
                            ),
                            "type": "Data",
                        }
                    ]
                },
                "type": "Section",
            },
            {
                "group": "Expenses",
                "Header": {"ColData": _cells("", "", "")},
                "Rows": {
                    "Row": [
                        {
                            # a parent account with a sub-account
                            "Header": {"ColData": _cells("", "", "", account=("3", "Utilities"))},
                            "Rows": {
                                "Row": [
                                    {
                                        "ColData": _cells(
                                            "125.00",
                                            "",
                                            "125.00",
                                            account=("4", "Gas and Electric"),
                                        ),
                                        "type": "Data",
                                    }
                                ]
                            },
                            "Summary": {"ColData": _cells("125.00", "", "125.00")},
                            "type": "Section",
                        }
                    ]
                },
                "type": "Section",
            },
        ]
    },
}


def _detail_column(key: str) -> dict[str, Any]:
    return {"ColTitle": key, "MetaData": [{"Name": "ColKey", "Value": key}]}


def _txn(when: str, kind: tuple[str, str], doc: str, name: str, amount: str) -> dict[str, Any]:
    return {
        "ColData": [
            {"value": when},
            {"value": kind[1], "id": kind[0]},
            {"value": doc},
            {"value": name, "id": "9"},
            {"value": ""},
            {"value": "Accounts Receivable"},
            {"value": amount},
            {"value": "0.00"},
        ],
        "type": "Data",
    }


DETAIL: dict[str, Any] = {
    "Columns": {
        "Column": [
            _detail_column(k)
            for k in (
                "tx_date",
                "txn_type",
                "doc_num",
                "name",
                "memo",
                "split_acc",
                "subt_nat_amount",
                "rbal_nat_amount",
            )
        ]
    },
    "Rows": {
        "Row": [
            {
                "Header": {"ColData": [{"value": "Income"}]},
                "Rows": {
                    "Row": [
                        {
                            "Header": {"ColData": [{"value": "Services", "id": "1"}]},
                            "Rows": {
                                "Row": [
                                    _txn("2026-08-05", ("130", "Invoice"), "1037", "Amy", "480.00"),
                                    # one invoice, two lines on the same account
                                    _txn("2026-09-03", ("131", "Invoice"), "1038", "Amy", "300.00"),
                                    _txn("2026-09-03", ("131", "Invoice"), "1038", "Amy", "250.00"),
                                    _txn(
                                        "2026-09-20", ("7", "Credit Memo"), "CM-1", "Amy", "-10.00"
                                    ),
                                ]
                            },
                            "Summary": {"ColData": [{"value": "Total Services"}]},
                            "type": "Section",
                        }
                    ]
                },
                "type": "Section",
            },
            {
                "Header": {"ColData": [{"value": "Subcontractors", "id": "2"}]},
                "Rows": {
                    "Row": [
                        _txn("2026-08-10", ("50", "Bill"), "B-1", "Apex", "288.00"),
                        _txn("2026-09-10", ("51", "Bill"), "B-2", "Apex", "318.00"),
                    ]
                },
                "type": "Section",
            },
            {
                "Header": {"ColData": [{"value": "Gas and Electric", "id": "4"}]},
                "Rows": {"Row": [_txn("2026-08-12", ("60", "Expense"), "", "PG&E", "125.00")]},
                "type": "Section",
            },
        ]
    },
}

ACCOUNTS = {
    "1": AccountClass.INCOME,
    "2": AccountClass.COST_OF_GOODS_SOLD,
    "3": AccountClass.EXPENSE,
    "4": AccountClass.EXPENSE,
}


def _reports() -> PnlReports:
    return PnlReports(by_month=BY_MONTH, detail=DETAIL, start="2026-08", end="2026-09")


def test_reports_become_gl_lines_and_their_transactions() -> None:
    gl_lines, txns, notes = build_pnl(_reports(), ACCOUNTS, {})
    assert notes == []
    amounts = {(g.account_id, g.period): g.amount for g in gl_lines}
    assert amounts[("1", "2026-09")] == Decimal("540.00")
    assert amounts[("4", "2026-09")] == Decimal(0)  # a blank cell: an explicit zero
    assert amounts[("3", "2026-08")] == Decimal(0)  # the parent's own (empty) row
    ids = {t.id for t in txns}
    assert {"Invoice-131:1", "Invoice-131:2", "Credit Memo-7", "Bill-51"} <= ids
    memo = next(t for t in txns if t.id == "Credit Memo-7")
    assert (memo.amount, memo.document_ref, memo.gl_line_id) == (
        Decimal("-10.00"),
        "CM-1",
        "QB-PL-1-2026-09",
    )
    line = next(g for g in gl_lines if g.id == "QB-PL-1-2026-09")
    assert line.transaction_ids == ["Invoice-131:1", "Invoice-131:2", "Credit Memo-7"]


def test_quickbooks_evidence_feeds_the_engine() -> None:
    gl_lines, txns, _ = build_pnl(_reports(), ACCOUNTS, {})
    doc = SnapshotDocument.model_validate(
        {
            "provenance": "SYNTHETIC_DEMO",
            "company_id": "9341",
            "company_name": "Sandbox",
            "entity": "US01",
            "currency": "USD",
            "basis": "Accrual",
            "as_of": "2026-10-02",
            "source_reference": "test",
            "accounts": [
                {"id": k, "name": f"A{k}", "classification": v.value} for k, v in ACCOUNTS.items()
            ],
            "gl_lines": [g.model_dump() for g in gl_lines],
            "transactions": [t.model_dump() for t in txns],
        }
    )
    pack = compute(doc, FpaSelection(start="2026-08", end="2026-09"))
    sep = pack["metrics"][-1]
    assert (sep["revenue"], sep["operating_expense"]) == (Decimal("540.00"), Decimal(0))
    # 300 + 250 - 10 = 540: the September invoice lines and the credit memo explain the GL
    assert pack["issues"] == []


def test_last_complete_months() -> None:
    assert last_complete_months(date(2026, 11, 2)) == ("2025-10", "2026-10")
    assert last_complete_months(date(2026, 1, 15), 3) == ("2025-10", "2025-12")


async def _source(db: AsyncSession, owner: User) -> Any:
    return await _connection(
        db,
        owner,
        {
            RecordType.CUSTOMER: [Customer(external_id="c1", name="Amy")],
            RecordType.INVOICE: [],
            RecordType.PAYMENT: [],
            RecordType.ACCOUNT: [
                Account(external_id="1", name="Services", account_type="Income"),
                Account(external_id="2", name="Subcontractors", account_type="Cost of Goods Sold"),
                Account(external_id="3", name="Utilities", account_type="Expense"),
                Account(external_id="4", name="Gas and Electric", account_type="Expense"),
            ],
        },
    )


async def _import(pod: AsyncClient, source: Any, entity: LegalEntity) -> Any:
    return await pod.post(
        "/api/v1/pod/snapshots/quickbooks",
        json={
            "data_source_id": str(source.id),
            "entity_id": str(entity.id),
            "currency": "USD",
            "basis": "Accrual",
        },
    )


async def test_snapshot_reads_the_pnl_and_opens_fpa(
    pod: AsyncClient,
    admin_user: User,
    entity: LegalEntity,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read(*_: Any) -> PnlReports:
        return _reports()

    monkeypatch.setattr(snapshot_service, "_read_pnl", fake_read)
    r = await _import(pod, await _source(db, admin_user), entity)
    assert r.status_code == 201, r.text
    snap = r.json()["snapshot"]
    assert {"accounts", "gl_lines", "transactions"} <= set(snap["coverage"])
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "fpa_trend",
            "snapshot_id": snap["id"],
            "title": "Aug-Sep",
            "selection": {"start": "2026-08", "end": "2026-09"},
        },
    )
    assert r.status_code == 201, r.text


async def test_without_report_access_the_snapshot_says_why(
    pod: AsyncClient, admin_user: User, entity: LegalEntity, db: AsyncSession
) -> None:
    # The test connection has no Intuit app credentials: the reports can't be read
    r = await _import(pod, await _source(db, admin_user), entity)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "gl_lines" not in body["snapshot"]["coverage"]
    assert any("FP&A" in n for n in body["notes"])
