"""AP-6 Month-End Close, end to end on a fictional October: a service received and not
billed (accrued), stock received and not billed (already in SRBNB), a rebate journalled to a
supplier's account (explains the payables difference) and a vendor statement with a line the
books don't have. Each rule is proved by a marked test."""

import io
import json
import uuid
import zipfile
from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.models import AuditEvent
from src.app.finance_pod.flows.ap_month_close import service as apc
from src.app.service_pod.core.cases.models import PodCase, PodReviewTask
from src.app.service_pod.core.snapshots.models import PodSnapshotSource
from tests.finance_pod.ap_data import ACCRUED, AP6_LEDGER, EXPENSE, LC, STATEMENT, ap6_payload
from tests.finance_pod.conftest import Cap, PersonFn, World, step
from tests.finance_pod.fake_erpnext import FakeErpNext
from tests.finance_pod.test_ap1 import act, ok, run
from tests.service_pod.conftest import import_snapshot

APC = "ap_month_close"
REVIEW = {"6.2.1.a": {"accruals_reviewed": True, "exceptions_reviewed": True}}
SIGN = {"6.2.2.a": {"approved": True}}


async def take(w: World, db: AsyncSession, **changes: Any) -> dict[str, Any]:
    assert w.admin and w.entity and w.source
    r = await import_snapshot(
        w.admin, w.entity, ap6_payload(source_reference=f"read {uuid.uuid4()}", **changes)
    )
    assert r.status_code in (200, 201), r.text
    snap: dict[str, Any] = r.json()["snapshot"]
    db.add(PodSnapshotSource(snapshot_id=uuid.UUID(snap["id"]), data_source_id=w.source.id))
    await db.commit()
    return snap


async def open_close(w: World, snap: dict[str, Any], period: str = "2026-10") -> Any:
    return await w["analyst"].post(
        "/api/v1/finance/cases",
        json={"workflow": APC, "snapshot_id": snap["id"], "title": f"AP close {period}",
              "selection": {"period": period}},
    )  # fmt: skip


async def controller(person: PersonFn) -> AsyncClient:
    _, client = await person("ctl@example.com", Cap.CONTROLLER)
    return client


def l5(case: dict[str, Any], key: str, i: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = step(case, key)["l5"][i]["result"]
    return out


async def prepared(w: World, db: AsyncSession, statement: bool = True, **changes: Any) -> Any:
    snap = await take(w, db, **changes)
    r = await open_close(w, snap)
    assert r.status_code == 201, r.text
    case = r.json()
    case = await run(w["analyst"], case, "6.1.1")
    case = await run(w["analyst"], case, "6.1.2")
    if statement:
        up = await w["analyst"].post(
            f"/api/v1/finance/cases/{case['id']}/artifacts",
            files={"file": ("labchem-oct.txt", STATEMENT.encode(), "text/plain")},
            data={"kind": "vendor_statement"},
        )
        assert up.status_code == 201, up.text
    return await run(w["analyst"], case, "6.1.3")


@pytest.mark.requirement("AP6.P1")
@pytest.mark.requirement("AP6.G1")
@pytest.mark.requirement("AP6.R3")
@pytest.mark.requirement("AP6.P3")
async def test_a_month_is_closed_from_accrual_to_posted_journal(
    world: World, db: AsyncSession, erp: FakeErpNext, person: PersonFn
) -> None:
    w = world
    ctl = await controller(person)
    case = await prepared(w, db)

    # 6.1.1: the service is accrued; the stock is already in SRBNB
    unbilled = l5(case, "6.1.1")
    assert {(x["order_id"], x["stock_item"], x["value"]) for x in unbilled["lines"]} == {
        ("PO-STOCK", True, "600.00"),
        ("PO-SVC", False, "900.00"),
    }
    assert (unbilled["stock_total"], unbilled["non_stock_total"]) == ("600.00", "900.00")
    proposal = l5(case, "6.1.1", 1)
    assert (proposal["posting_date"], proposal["reversal_date"]) == ("2026-10-31", "2026-11-01")
    assert [(x["account_id"], x["debit"], x["credit"]) for x in proposal["lines"]] == [
        (EXPENSE, "900.00", "0"),
        (ACCRUED, "0", "900.00"),
    ]

    # 6.1.2: 702 in the ledger vs 802 of open invoices, explained by the rebate journal
    comparisons = {x["ledger"]: x for x in l5(case, "6.1.2")["comparisons"]}
    assert comparisons["payable"]["difference"] == "-100.00"
    assert comparisons["received_not_billed"]["difference"] == "0.00"
    explained = l5(case, "6.1.2", 1)
    assert explained["unexplained"] == "0"
    assert [x["voucher"] for x in explained["items"]] == ["Journal Entry JE-REBATE"]

    # 6.1.3: LabChem's statement has an invoice the books don't
    check = l5(case, "6.1.3")
    read = check["statements"][0]
    assert (read["vendor_id"], read["closing_balance"], read["books_balance"]) == (
        LC, "815.00", "760.00",
    )  # fmt: skip
    assert [(g["reference"], g["kind"]) for g in read["gaps"]] == [("LC5099", "not_in_books")]
    assert (check["missing"], check["gaps"]) == ([], 1)

    # 6.2: only the controller reviews and signs; sign-off releases the close
    r = await act(w["analyst"], case, "complete_step", step="6.2.1", results=REVIEW)
    assert r.status_code == 409 and "controller" in r.text
    case = await ok(ctl, case, "complete_step", step="6.2.1", results=REVIEW)
    case = await ok(ctl, case, "complete_step", step="6.2.2", results=SIGN)
    assert case["status"] == "approved"

    # AP6.R3: the evidence pack is filed, its manifest naming every file's SHA-256
    pack = next(a for a in case["artifacts"] if a["kind"] == "evidence")
    data = (await ctl.get(f"/api/v1/finance/artifacts/{pack['id']}/content")).content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert set(manifest) == {"case.json", "steps.json", "review_tasks.json", "audit.json"}
        steps = json.loads(z.read("steps.json"))
        audit = json.loads(z.read("audit.json"))
    assert {s["l5"] for s in steps} >= {"6.1.1.b", "6.1.2.b", "6.1.3.a", "6.2.2.a"}
    assert any(e["type"] == "pod.case_complete_step" for e in audit)

    # AP6.G1: the agent proposed; only the controller posts
    tasks = case["posting_tasks"]
    assert [(t["kind"], t["status"]) for t in tasks] == [("create_journal_entry", "proposed")] * 2
    assert not erp.inserted
    accrual = next(t for t in tasks if t["reference"].endswith("accrual"))
    post = {"action": "post", "expected_version": accrual["version"]}
    r = await w["analyst"].post(f"/api/v1/finance/tasks/{accrual['id']}/actions", json=post)
    assert r.status_code == 403, r.text
    r = await ctl.post(f"/api/v1/finance/tasks/{accrual['id']}/actions", json=post)
    assert r.status_code == 200, r.text
    journal = erp.inserted[-1]
    assert (journal["doctype"], journal["posting_date"]) == ("Journal Entry", "2026-10-31")
    assert journal["accounts"][1] == {
        "account": ACCRUED, "debit_in_account_currency": "0",
        "credit_in_account_currency": "900.00",
    }  # fmt: skip
    case = (await ctl.get(f"/api/v1/finance/cases/{case['id']}")).json()
    assert case["completion_blockers"]  # until both journals are verified

    reversal = next(t for t in case["posting_tasks"] if t["reference"].endswith("reversal"))
    post = {"action": "post", "expected_version": reversal["version"]}
    r = await ctl.post(f"/api/v1/finance/tasks/{reversal['id']}/actions", json=post)
    assert r.status_code == 200, r.text
    assert erp.inserted[-1]["posting_date"] == "2026-11-01"
    detail = (await ctl.get(f"/api/v1/finance/cases/{case['id']}")).json()
    posted = detail["posting_tasks"]
    fresh = await take(
        w, db,
        journal_entries=[
            {"id": t["external_txn_id"], "posting_date": "2026-10-31", "doc_status": "Submitted",
             "total": "900", "reference": t["reference"]}
            for t in posted
        ],
    )  # fmt: skip
    for t in posted:
        verify = {"action": "verify", "expected_version": t["version"], "snapshot_id": fresh["id"]}
        r = await ctl.post(f"/api/v1/finance/tasks/{t['id']}/actions", json=verify)
        assert r.status_code == 200, r.text
    case = await ok(ctl, case, "complete")
    assert case["status"] == "completed"
    tiles = (await ctl.get("/api/v1/finance/dashboard")).json()["workflows"]
    days = next(m for t in tiles if t["key"] == APC for m in t["measures"] if m["id"] == "AP6.M1")
    assert days["value"] is not None


@pytest.mark.requirement("AP6.R2")
async def test_an_unexplained_difference_needs_the_controllers_word(
    world: World, db: AsyncSession, person: PersonFn
) -> None:
    w = world
    ctl = await controller(person)
    ledger = [dict(b) for b in AP6_LEDGER["ledger_balances"]]
    ledger[0]["balance"] = "750"  # 48 more than the invoices and the rebate explain
    case = await prepared(w, db, ledger_balances=ledger)
    assert l5(case, "6.1.2", 1)["unexplained"] == "48.00"
    case = await ok(ctl, case, "complete_step", step="6.2.1", results=REVIEW)
    case = await ok(ctl, case, "complete_step", step="6.2.2", results=SIGN)
    assert case["status"] == "draft"
    assert any("AP6.R2" in b for b in case["blockers"])

    case = await ok(ctl, case, "redo_step", step="6.2.1", reason="Say why the 48 is open")
    with_comment = {"6.2.1.a": {**REVIEW["6.2.1.a"], "comment": "Freight accrual, in Nov"}}
    case = await ok(ctl, case, "complete_step", step="6.2.1", results=with_comment)
    case = await ok(ctl, case, "complete_step", step="6.2.2", results=SIGN)
    assert case["status"] == "approved"


@pytest.mark.requirement("AP6.R2")
async def test_one_close_per_month_on_a_snapshot_after_it(world: World, db: AsyncSession) -> None:
    w = world
    snap = await take(w, db)
    assert (await open_close(w, snap)).status_code == 201
    again = await open_close(w, snap)
    assert again.status_code == 422 and "already being closed" in again.text
    early = await open_close(w, snap, "2026-11")
    assert early.status_code == 422 and "take one after 2026-11-30" in early.text
    assert (await open_close(w, snap, "2026-13")).status_code == 422


async def test_the_signer_is_not_who_prepared_the_close(
    world: World, db: AsyncSession, grant: Any
) -> None:
    w = world
    await grant(w.users["analyst"], Cap.CONTROLLER)
    case = await prepared(w, db)
    case = await ok(w["analyst"], case, "complete_step", step="6.2.1", results=REVIEW)
    r = await act(w["analyst"], case, "complete_step", step="6.2.2", results=SIGN)
    assert r.status_code in (403, 409), r.text


async def test_a_key_vendor_without_a_statement_is_flagged(world: World, db: AsyncSession) -> None:
    case = await prepared(world, db, statement=False)
    assert l5(case, "6.1.3") == {"statements": [], "missing": [LC], "gaps": 1}


@pytest.mark.requirement("AP6.R1")
@pytest.mark.requirement("AP6.P2")
@pytest.mark.requirement("AP6.G2")
async def test_the_close_is_checked_daily(world: World, db: AsyncSession) -> None:
    w = world
    case = await prepared(w, db)
    row = await db.get(PodCase, uuid.UUID(case["id"]))
    assert row is not None

    await apc.check_close(db, row, date(2026, 11, 4))
    await db.commit()
    assert row.state["_daily"]["unexplained"] == "0.00"

    # A late adjustment lands in the ledger: tomorrow's check flags it before the close
    ledger = [dict(b) for b in AP6_LEDGER["ledger_balances"]]
    ledger[0] |= {"balance": "690", "as_of": "2026-11-04"}
    await take(w, db, as_of="2026-11-04", ledger_balances=ledger)
    await apc.check_close(db, row, date(2026, 11, 5))
    await db.commit()

    # Past the close day of November and still not signed off
    await apc.check_close(db, row, date(2026, 11, 6))
    await db.commit()
    subjects = list(
        await db.scalars(select(PodReviewTask.subject).where(PodReviewTask.case_id == row.id))
    )
    assert subjects == ["Reconciliation moved", "Close deadline"]
    assert row.state["_deadline_missed"] == "2026-11-05"

    events = list(
        await db.scalars(
            select(AuditEvent.event_type).where(AuditEvent.details["run"].astext == row.reference)
        )
    )
    assert events.count("pod.case_run_agent_step") == 3

    tiles = (await w["analyst"].get("/api/v1/finance/dashboard")).json()["workflows"]
    measures = {m["id"]: m["value"] for t in tiles if t["key"] == APC for m in t["measures"]}
    assert (measures["AP6.M2"], measures["AP6.M3"]) == ("2.0", "2")
