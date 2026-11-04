"""Financial Reporting (TDD section 10): statements and controls, the Controller and CFO
sign-offs, the immutable PDF pack and its internal distribution."""

import copy
import hashlib
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import get_settings
from src.app.entities.models import LegalEntity
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.snapshots.importers.quickbooks_pnl import (
    PnlReports,
    build_balance_sheets,
    build_close_status,
)
from src.app.service_pod.flows.reporting.engine import compute
from src.app.service_pod.flows.reporting.models import PodReportPack
from src.app.service_pod.flows.reporting.schemas import ReportingSelection
from tests.conftest import FakeLLM
from tests.service_pod.conftest import act, import_snapshot
from tests.service_pod.fpa_data import fpa_document

SEP = ReportingSelection(month="2026-09")


def report_document(**changes: Any) -> dict[str, Any]:
    """The deck dataset plus month-end Balance Sheets, the close status and open invoices."""
    doc = fpa_document(
        balance_sheets=[
            {
                "period": "2026-08",
                "assets": "1250000",
                "liabilities": "450000",
                "equity": "800000",
                "report_id": "BS-2026-08",
            },
            {
                "period": "2026-09",
                "assets": "1320000",
                "liabilities": "435000",
                "equity": "885000",
                "report_id": "BS-2026-09",
            },
        ],
        close_status=[
            {"period": "2026-08", "status": "Closed"},
            {"period": "2026-09", "status": "Closed", "required_checks": ["Accrual cutoff"]},
        ],
        customers=[{"id": "C1", "name": "Harbor Distribution"}],
        invoices=[
            {
                "id": "I1",
                "number": "INV-401",
                "customer_id": "C1",
                "txn_date": "2026-09-10",
                "due_date": "2026-10-10",
                "original_amount": "200000",
                "balance": "120000",
            },
            {
                "id": "I2",
                "number": "INV-381",
                "customer_id": "C1",
                "txn_date": "2026-08-10",
                "due_date": "2026-09-09",
                "original_amount": "200000",
                "balance": "15000",
            },
        ],
    )
    doc.update(changes)
    return doc


def _doc(**changes: Any) -> SnapshotDocument:
    return SnapshotDocument.model_validate(report_document(**changes))


# --- the engine ------------------------------------------------------------------------


def test_statements_and_controls_for_a_closed_balanced_month() -> None:
    pack = compute(_doc(), SEP)
    assert (pack["report_month"], pack["prior_month"]) == ("2026-09", "2026-08")
    assert [m["period"] for m in pack["metrics"]] == ["2026-08", "2026-09"]
    assert pack["metrics"][-1]["margin_pct"] == Decimal("15.7407")
    assert pack["issues"] == []
    assert all(c["status"] == "pass" for c in pack["controls"])
    aging = pack["aging"]
    # as of the snapshot's own date (5 Oct), not relabelled as the September month end
    assert (str(aging["as_of"]), aging["matches_month_end"]) == ("2026-10-05", False)
    assert aging["total"] == Decimal(135000)
    assert [b["count"] for b in aging["buckets"]] == [1, 1, 0, 0, 0]  # INV-381: 26 days


def test_unbalanced_or_missing_sheets_and_an_open_month_block() -> None:
    doc = report_document()
    doc["balance_sheets"][1]["equity"] = "884999.99"  # one cent: beyond half a cent
    doc["balance_sheets"] = doc["balance_sheets"][1:]  # and August's is missing
    doc["close_status"][1]["status"] = "Open"
    pack = compute(SnapshotDocument.model_validate(doc), SEP)
    codes = sorted(i["code"] for i in pack["issues"] if i["blocking"])
    assert codes == ["balance_sheet_count", "balance_sheet_unbalanced", "period_open"]


def test_a_cent_off_is_beyond_the_half_cent_tolerance() -> None:
    doc = report_document()
    doc["balance_sheets"][1]["equity"] = "884999.99"
    issues = compute(SnapshotDocument.model_validate(doc), SEP)["issues"]
    assert [i["code"] for i in issues] == ["balance_sheet_unbalanced"]


def test_the_prior_month_must_be_in_the_source() -> None:
    with pytest.raises(CaseSelectionError, match="2026-03"):
        compute(_doc(), ReportingSelection(month="2026-04"))


# --- the case flow ---------------------------------------------------------------------


@pytest.fixture
async def report_snapshot(pod: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(pod, entity, report_document())
    assert r.status_code == 201, r.text
    return r.json()["snapshot"]  # type: ignore[no-any-return]


async def _open(pod: AsyncClient, snapshot: dict[str, Any], month: str = "2026-09") -> Any:
    return await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "reporting",
            "snapshot_id": snapshot["id"],
            "title": "September 2026 pack",
            "selection": {"month": month},
        },
    )


COMMENTARY = {
    "highlights": [
        {
            "text": "Revenue rose, led by the new Fabrikam invoice, partly offset by Contoso.",
            "fact_ids": ["change.revenue", "revenue_driver.1"],
        },
        {
            "text": "The balance sheet stays balanced and the month is closed.",
            "fact_ids": ["balance_sheet.assets.2026-09", "close.status"],
        },
    ],
    "follow_ups": [
        {
            "kind": "question",
            "text": "Confirm the accrual cutoff for September.",
            "fact_ids": ["close.status"],
        }
    ],
}


async def _ready(pod: AsyncClient, snapshot: dict[str, Any], llm: FakeLLM) -> dict[str, Any]:
    """A September case with its commentary and the aging scope task settled."""
    case = (await _open(pod, snapshot)).json()
    llm.output = COMMENTARY
    r = await pod.post(
        f"/api/v1/pod/fpa/cases/{case['id']}/commentary",
        json={"expected_version": case["version"]},
    )
    assert r.status_code == 200, r.text
    case = r.json()
    (scope,) = [t for t in case["review_tasks"] if t["kind"] == "scope"]
    r = await act(
        pod,
        case,
        "resolve_review_task",
        task_id=scope["id"],
        resolution="Kept as a disclosed limitation: aging is as of 5 October.",
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_aging_date_raises_a_scope_task_that_blocks(
    pod: AsyncClient, report_snapshot: dict[str, Any], fake_llm: FakeLLM
) -> None:
    r = await _open(pod, report_snapshot)
    assert r.status_code == 201, r.text
    case = r.json()
    (scope,) = case["review_tasks"]
    assert (scope["kind"], scope["blocking"], scope["subject"]) == ("scope", True, "AR aging date")
    assert "2026-10-05" in scope["detail"]
    assert case["stage"] == "statements"
    assert case["next_signoff"] == "Controller"
    fake_llm.output = COMMENTARY
    case = (
        await pod.post(
            f"/api/v1/pod/fpa/cases/{case['id']}/commentary",
            json={"expected_version": case["version"]},
        )
    ).json()
    assert case["allowed_actions"]["approve"] is not None  # the scope task is still open
    assert any("review task" in b for b in case["blockers"])


async def test_controller_then_cfo_then_the_pack(
    pod: AsyncClient, report_snapshot: dict[str, Any], fake_llm: FakeLLM, db: AsyncSession
) -> None:
    case = await _ready(pod, report_snapshot, fake_llm)
    assert case["stage"] == "controller" and case["allowed_actions"]["approve"] is None

    # No pack before both sign-offs
    r = await pod.post(f"/api/v1/pod/reporting/cases/{case['id']}/packs")
    assert r.status_code == 409

    case = (await act(pod, case, "approve")).json()
    assert [a["capacity"] for a in case["approvals"]] == ["Controller"]
    assert (case["status"], case["next_signoff"], case["stage"]) == ("draft", "CFO", "cfo")

    case = (await act(pod, case, "approve")).json()
    assert [a["capacity"] for a in case["approvals"]] == ["Controller", "CFO"]
    assert (case["status"], case["next_signoff"]) == ("approved", None)
    assert (await act(pod, case, "approve")).status_code == 409  # nothing left to sign
    assert "PDF pack" in case["completion_blockers"][0]

    r = await pod.post(f"/api/v1/pod/reporting/cases/{case['id']}/packs")
    assert r.status_code == 200, r.text
    pack = r.json()
    assert pack["number"] == 1 and pack["current"] is True
    assert [p["capacity"] for p in pack["reviewers"]] == ["Controller", "CFO"]
    again = (await pod.post(f"/api/v1/pod/reporting/cases/{case['id']}/packs")).json()
    assert again["id"] == pack["id"]  # the same content is exported once

    pdf = await pod.get(f"/api/v1/pod/reporting/cases/{case['id']}/packs/{pack['id']}.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-1.4") and pdf.content.rstrip().endswith(b"%%EOF")
    assert hashlib.sha256(pdf.content).hexdigest() == pack["sha256"]
    assert b"Signed off as CFO" in pdf.content and b"15.7%" in pdf.content

    case = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    assert case["allowed_actions"]["complete"] is None

    # Bytes altered at rest: refused, never served
    await db.execute(
        update(PodReportPack).where(PodReportPack.case_id == case["id"]).values(pdf=b"%PDF-forged")
    )
    await db.commit()
    r = await pod.get(f"/api/v1/pod/reporting/cases/{case['id']}/packs/{pack['id']}.pdf")
    assert r.status_code == 409


async def test_an_edit_after_sign_off_leaves_the_pack_as_history(
    pod: AsyncClient, entity: LegalEntity, report_snapshot: dict[str, Any], fake_llm: FakeLLM
) -> None:
    case = await _ready(pod, report_snapshot, fake_llm)
    case = (await act(pod, case, "approve")).json()
    case = (await act(pod, case, "approve")).json()
    first = (await pod.post(f"/api/v1/pod/reporting/cases/{case['id']}/packs")).json()

    newer = (
        await import_snapshot(
            pod, entity, report_document(source_reference="re-export", as_of="2026-10-06")
        )
    ).json()["snapshot"]
    case = (await act(pod, case, "refresh_source", snapshot_id=newer["id"])).json()
    assert case["status"] == "draft"
    assert case["next_signoff"] == "Controller"  # both sign-offs are needed again
    packs = (await pod.get(f"/api/v1/pod/reporting/cases/{case['id']}/packs")).json()
    assert [(p["id"], p["current"]) for p in packs] == [(first["id"], False)]


async def test_the_pack_goes_only_to_internal_recipients(
    pod: AsyncClient,
    report_snapshot: dict[str, Any],
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _ready(pod, report_snapshot, fake_llm)
    case = (await act(pod, case, "approve")).json()
    case = (await act(pod, case, "approve")).json()
    compose = {"purpose": "pack_distribution"}
    r = await pod.post(f"/api/v1/pod/cases/{case['id']}/messages/compose", json=compose)
    assert r.status_code == 409 and "PDF pack" in r.json()["detail"]["message"]
    pack = (await pod.post(f"/api/v1/pod/reporting/cases/{case['id']}/packs")).json()

    r = await pod.post(f"/api/v1/pod/cases/{case['id']}/messages/compose", json=compose)
    assert r.status_code == 409 and "internal recipients" in r.json()["detail"]["message"]

    monkeypatch.setattr(get_settings(), "pod_internal_recipients", ["cfo@example.com"])
    draft = (
        await pod.post(f"/api/v1/pod/cases/{case['id']}/messages/compose", json=compose)
    ).json()
    assert draft["to_email"] == "cfo@example.com"
    message = {
        "audience": "internal",
        "purpose": "pack_distribution",
        "to_email": draft["to_email"],
        "subject": draft["subject"],
        "body": draft["body"],
        "artifact_ids": [pack["artifact_id"]],
    }
    r = await pod.post(
        f"/api/v1/pod/cases/{case['id']}/messages", json=message | {"to_email": "x@other.com"}
    )
    assert r.status_code == 409  # only a configured internal recipient, from the draft on
    saved = (await pod.post(f"/api/v1/pod/cases/{case['id']}/messages", json=message)).json()
    r = await pod.post(
        f"/api/v1/pod/messages/{saved['id']}/send",
        json={"expected_version": saved["version"], "checks": {}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent"


async def test_report_months_screen(pod: AsyncClient, report_snapshot: dict[str, Any]) -> None:
    body = (await pod.get("/api/v1/pod/reporting/months")).json()
    (source,) = body["sources"]
    assert source["suggested"] == "2026-09"
    sep = next(m for m in source["months"] if m["month"] == "2026-09")
    assert sep == {
        "month": "2026-09",
        "closed": True,
        "balance_sheet": True,
        "prior_available": True,
    }
    assert next(m for m in source["months"] if m["month"] == "2026-04")["prior_available"] is False


def test_quickbooks_balance_sheet_and_close_status() -> None:
    def month(start: str, end: str) -> dict[str, Any]:
        return {
            "MetaData": [{"Name": "StartDate", "Value": start}, {"Name": "EndDate", "Value": end}]
        }

    def summary(*values: str) -> dict[str, Any]:
        return {"ColData": [{"value": ""}, *({"value": v} for v in values)]}

    report = {
        "Columns": {
            "Column": [
                {"ColTitle": ""},
                month("2026-08-01", "2026-08-31"),
                month("2026-09-01", "2026-09-30"),
            ]
        },
        "Rows": {
            "Row": [
                {"group": "TotalAssets", "Summary": summary("1250.00", "1320.00")},
                {
                    "group": "TotalLiabilitiesAndEquity",
                    "Rows": {
                        "Row": [
                            {"group": "Liabilities", "Summary": summary("450.00", "435.00")},
                            {"group": "Equity", "Summary": summary("800.00", "885.00")},
                        ]
                    },
                    "Summary": summary("1250.00", "1320.00"),
                },
            ]
        },
    }
    reports = PnlReports(
        by_month={},
        detail={},
        start="2026-08",
        end="2026-09",
        balance_sheet=copy.deepcopy(report),
        books_closed_through="2026-08-31",
    )
    sheets = build_balance_sheets(reports)
    assert sheets is not None
    assert [(b.period, b.assets, b.liabilities, b.equity) for b in sheets] == [
        ("2026-08", Decimal("1250.00"), Decimal("450.00"), Decimal("800.00")),
        ("2026-09", Decimal("1320.00"), Decimal("435.00"), Decimal("885.00")),
    ]
    assert [(c.period, c.status) for c in build_close_status(reports)] == [
        ("2026-08", "Closed"),
        ("2026-09", "Open"),
    ]
