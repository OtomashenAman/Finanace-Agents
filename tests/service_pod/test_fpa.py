"""FP&A Trend Intelligence: the engine's arithmetic (TDD section 8) and the case flow."""

import copy
import json
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from src.app.entities.models import LegalEntity
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.flows.fpa_trend.engine import compute, pct_change, suggested_range
from src.app.service_pod.flows.fpa_trend.schemas import FpaSelection
from tests.conftest import FakeLLM
from tests.service_pod.conftest import act, import_snapshot
from tests.service_pod.fpa_data import fpa_document

FULL = FpaSelection(start="2026-04", end="2026-09")


def _doc(**changes: Any) -> SnapshotDocument:
    return SnapshotDocument.model_validate(fpa_document(**changes))


def _without(doc: dict[str, Any], account: str, period: str) -> dict[str, Any]:
    """The export with one account's GL line (and its transactions) left out."""
    gl_id = f"GL-{account}-{period}"
    doc["gl_lines"] = [g for g in doc["gl_lines"] if g["id"] != gl_id]
    doc["transactions"] = [t for t in doc["transactions"] if t.get("gl_line_id") != gl_id]
    return doc


# --- the engine ------------------------------------------------------------------------


def test_deck_figures_and_the_exact_margin_shift() -> None:
    pack = compute(_doc(), FULL)
    sep = pack["metrics"][-1]
    assert (sep["revenue"], sep["operating_profit"]) == (Decimal(540000), Decimal(85000))
    assert sep["margin_pct"] == Decimal("15.7407")
    change = pack["changes"][-1]
    # Exact (1.7824 pp) and between the displayed rounded margins (1.7 pp): both kept
    assert change["margin_pp_exact"] == Decimal("1.7824")
    assert change["margin_pp_displayed"] == Decimal("1.7")
    # Source arithmetic over the mockup: opex +9.6% (not 9.8%), total cost ~10.17%
    assert change["operating_expense"]["pct"] == Decimal("9.6000")
    assert change["total_operating_cost"]["pct"] == Decimal("10.1695")
    bridge = change["bridge"]
    assert (bridge["from_profit"], bridge["to_profit"]) == (Decimal(67000), Decimal(85000))
    assert (bridge["revenue"], bridge["cost_of_services"], bridge["operating_expense"]) == (
        Decimal(60000),
        Decimal(-30000),
        Decimal(-12000),
    )
    assert bridge["reconciles"] is True
    assert change["outlier"] is True  # revenue +12.5%: at least 10%
    assert pack["issues"] == []


def test_drivers_are_posted_transactions_with_their_evidence() -> None:
    change = compute(_doc(), FULL)["changes"][-1]
    drivers = {d["counterparty"]: d for d in change["revenue_drivers"]}
    assert drivers["Fabrikam Enterprise"]["change"] == Decimal(42000)
    assert drivers["Northwind Traders"]["change"] == Decimal(26000)
    # The credit memo stays signed: Contoso's base declines by 8k
    assert drivers["Contoso Ltd"]["change"] == Decimal(-8000)
    memo = next(t for t in drivers["Contoso Ltd"]["transactions"] if t["type"] == "CreditMemo")
    assert (memo["amount"], memo["document_ref"], memo["gl_line_id"]) == (
        Decimal(-8000),
        "CM-404",
        "GL-A4000-2026-09",
    )
    costs = {d["account"]: d["change"] for d in change["cost_drivers"]}
    assert costs == {
        "Subcontractors": Decimal(30000),
        "Operating payroll": Decimal(7000),
        "Cloud and tools": Decimal(3000),
        "Other operating costs": Decimal(2000),
    }
    # The draft bill is never a driver
    apex = next(d for d in change["cost_drivers"] if d["account"] == "Subcontractors")
    assert all(t["id"] != "T-B-499" for c in apex["contributors"] for t in c["transactions"])


def test_non_operating_and_drafts_are_disclosed_not_counted() -> None:
    pack = compute(_doc(), FULL)
    assert pack["metrics"][0]["revenue"] == Decimal(420000)  # interest income left out
    assert pack["metrics"][0]["other_income"] == Decimal(500)
    assert any("OtherIncome" in c for c in pack["caveats"])
    assert any("Posted transactions only" in c for c in pack["caveats"])


def test_a_skipped_month_is_refused() -> None:
    doc = fpa_document()
    doc["gl_lines"] = [g for g in doc["gl_lines"] if g["period"] != "2026-06"]
    doc["transactions"] = [t for t in doc["transactions"] if t["period"] != "2026-06"]
    with pytest.raises(CaseSelectionError, match="2026-06"):
        compute(SnapshotDocument.model_validate(doc), FULL)


def test_an_absent_category_blocks_instead_of_becoming_zero() -> None:
    doc = _without(fpa_document(), "A5000", "2026-07")
    pack = compute(SnapshotDocument.model_validate(doc), FULL)
    blocking = [i for i in pack["issues"] if i["blocking"]]
    assert [i["code"] for i in blocking] == ["missing_category"]
    assert "2026-07" in blocking[0]["detail"] and "CostOfGoodsSold" in blocking[0]["detail"]


def test_an_unexplained_gl_movement_blocks() -> None:
    doc = fpa_document()
    line = next(g for g in doc["gl_lines"] if g["id"] == "GL-A6200-2026-09")
    line["amount"] = "24500"  # 1,500 more than its transactions
    pack = compute(SnapshotDocument.model_validate(doc), FULL)
    (issue,) = [i for i in pack["issues"] if i["code"] == "unexplained_delta"]
    assert issue["blocking"] and "Cloud and tools" in issue["detail"]
    assert pack["changes"][-1]["unexplained"][0]["difference"] == Decimal(1500)


def test_zero_baselines_are_undefined() -> None:
    assert pct_change(Decimal(5), Decimal(0)) is None
    doc = fpa_document()
    for g in doc["gl_lines"]:
        if g["account_id"] == "A4000" and g["period"] == "2026-04":
            g["amount"] = "0"
            ids = set(g["transaction_ids"])
            g["transaction_ids"] = []
    doc["transactions"] = [t for t in doc["transactions"] if t["id"] not in ids]
    pack = compute(SnapshotDocument.model_validate(doc), FULL)
    assert pack["metrics"][0]["margin_pct"] is None
    assert pack["changes"][0]["revenue"]["pct"] is None
    assert pack["changes"][0]["margin_pp_exact"] is None


def test_yoy_and_seasonality_only_when_sourced() -> None:
    pack = compute(_doc(), FULL)
    assert pack["yoy"] == [] and pack["seasonality"] is None
    doc = fpa_document()
    extra = copy.deepcopy(next(g for g in doc["gl_lines"] if g["id"] == "GL-A4000-2026-09"))
    extra |= {"id": "GL-A4000-2025-09", "period": "2025-09", "amount": "450000"}
    extra["transaction_ids"] = []
    doc["gl_lines"].append(extra)
    (yoy,) = compute(SnapshotDocument.model_validate(doc), FULL)["yoy"]
    assert (yoy["period"], yoy["prior_period"], yoy["revenue_pct"]) == (
        "2026-09",
        "2025-09",
        Decimal("20.0000"),
    )


def test_suggested_range_is_the_latest_six_consecutive_months() -> None:
    assert suggested_range(["2026-01", "2026-02", *[f"2026-0{m}" for m in range(4, 10)]]) == (
        "2026-04",
        "2026-09",
    )
    assert suggested_range(["2026-01"]) is None


# --- the case flow ---------------------------------------------------------------------


@pytest.fixture
async def fpa_snapshot(pod: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(pod, entity, fpa_document())
    assert r.status_code == 201, r.text
    return r.json()["snapshot"]  # type: ignore[no-any-return]


async def _open(pod: AsyncClient, snapshot: dict[str, Any], **sel: Any) -> dict[str, Any]:
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "fpa_trend",
            "snapshot_id": snapshot["id"],
            "title": "Apr-Sep 2026 trends",
            "selection": {"start": "2026-04", "end": "2026-09", **sel},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


COMMENTARY = {
    "highlights": [
        {
            "text": "Revenue grew, led by the new Fabrikam invoice and expanded Northwind work.",
            "fact_ids": ["change.revenue", "revenue_driver.1", "revenue_driver.2"],
        },
        {
            "text": "Subcontractor costs rose but revenue grew faster, so the margin improved.",
            "fact_ids": ["cost_driver.A5000", "change.margin"],
        },
    ],
    "follow_ups": [
        {
            "kind": "question",
            "text": "Is the new Fabrikam revenue recurring?",
            "fact_ids": ["revenue_driver.1"],
        },
        {
            "kind": "investigate",
            "text": "Investigate the subcontractor rate increase.",
            "fact_ids": ["cost_driver.A5000"],
        },
    ],
}


async def _commentary(pod: AsyncClient, case: dict[str, Any]) -> Any:
    return await pod.post(
        f"/api/v1/pod/fpa/cases/{case['id']}/commentary",
        json={"expected_version": case["version"]},
    )


async def test_periods_screen_lists_sources_and_cases(
    pod: AsyncClient, fpa_snapshot: dict[str, Any]
) -> None:
    case = await _open(pod, fpa_snapshot)
    body = (await pod.get("/api/v1/pod/fpa/periods")).json()
    (source,) = body["sources"]
    assert source["months"][0] == "2026-04" and source["months"][-1] == "2026-09"
    assert (source["suggested_start"], source["suggested_end"]) == ("2026-04", "2026-09")
    assert [c["reference"] for c in body["cases"]] == [case["reference"]]


async def test_case_runs_from_analysis_to_finance_head_sign_off(
    pod: AsyncClient, fpa_snapshot: dict[str, Any], fake_llm: FakeLLM
) -> None:
    case = await _open(pod, fpa_snapshot)
    assert case["stage"] == "analysis"
    assert "commentary" in case["blockers"][0]
    assert case["allowed_actions"]["approve"] is not None

    # A model that states a figure itself is rejected; nothing is stored
    bad = copy.deepcopy(COMMENTARY)
    bad["highlights"][0]["text"] = "Revenue grew by 12.5% in September."
    fake_llm.output = bad
    r = await _commentary(pod, case)
    assert r.status_code == 422
    assert "states a figure" in r.json()["detail"]["message"]
    assert len(fake_llm.calls) == 2  # retried once, told what was wrong

    # ...and so is one that writes the figure out in words
    worded = copy.deepcopy(COMMENTARY)
    worded["highlights"][0]["text"] = "Revenue rose by sixty thousand dollars in September."
    fake_llm.output = worded
    r = await _commentary(pod, case)
    assert r.status_code == 422

    fake_llm.output = COMMENTARY
    r = await _commentary(pod, case)
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["state"]["commentary"]["by"] == "ai"
    # Questions and checks stay with the commentary: no review tasks, nothing in My Queue
    assert [f["kind"] for f in case["state"]["follow_ups"]] == ["question", "investigate"]
    assert case["review_tasks"] == []
    assert case["stage"] == "signoff"
    assert case["allowed_actions"]["approve"] is None

    d = (await pod.get("/api/v1/pod/dashboard")).json()
    assert d["phases"]["ready"] == 1

    r = await act(pod, case, "approve")
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["approvals"][0]["capacity"] == "Finance Head"

    pack = await pod.get(f"/api/v1/pod/fpa/cases/{case['id']}/pack.json")
    assert pack.status_code == 200, pack.text
    body = pack.json()
    assert body["signed_off"]["as"] == "Finance Head"
    assert body["metrics"][-1]["margin_pct"] == "15.7407"

    evidence = await pod.get(f"/api/v1/pod/fpa/cases/{case['id']}/evidence.csv")
    assert evidence.status_code == 200
    assert "CM-404" in evidence.text and "T-INV-411" in evidence.text


async def test_pack_is_refused_before_sign_off(
    pod: AsyncClient, fpa_snapshot: dict[str, Any]
) -> None:
    case = await _open(pod, fpa_snapshot)
    r = await pod.get(f"/api/v1/pod/fpa/cases/{case['id']}/pack.json")
    assert r.status_code == 409


async def test_commentary_by_hand_and_mapping_review(
    pod: AsyncClient, fpa_snapshot: dict[str, Any]
) -> None:
    case = await _open(pod, fpa_snapshot)
    r = await act(
        pod,
        case,
        "set_commentary",
        highlights=[{"text": "Revenue +60k, two accounts.", "fact_ids": ["nope"]}],
    )
    assert r.status_code == 422
    case = (
        await act(
            pod,
            case,
            "set_commentary",
            highlights=[
                {"text": "Revenue +60k from two accounts.", "fact_ids": ["change.revenue"]}
            ],
        )
    ).json()
    assert case["state"]["commentary"]["by"] == "hand"
    case = (
        await act(pod, case, "confirm_mapping", note="Checked with the chart of accounts")
    ).json()
    assert case["state"]["mapping_review"]["accounts"] == 6
    assert case["allowed_actions"]["approve"] is None


async def test_blocking_data_issue_holds_the_case(pod: AsyncClient, entity: LegalEntity) -> None:
    r = await import_snapshot(pod, entity, _without(fpa_document(), "A5000", "2026-07"))
    case = await _open(pod, r.json()["snapshot"])
    assert case["stage"] == "data"
    assert any("CostOfGoodsSold" in b for b in case["blockers"])
    r = await _commentary(pod, case)
    assert r.status_code == 409


async def test_skipped_month_refuses_the_case(
    pod: AsyncClient, fpa_snapshot: dict[str, Any]
) -> None:
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "fpa_trend",
            "snapshot_id": fpa_snapshot["id"],
            "title": "Too early",
            "selection": {"start": "2026-02", "end": "2026-09"},
        },
    )
    assert r.status_code == 422
    assert "2026-02" in r.json()["detail"]["message"]


CORRECTION: dict[str, Any] = {
    "period": "2026-09",
    "evidence_gl_line_id": "GL-A6200-2026-09",
    "rationale": "A 3,000 software licence for October was booked in September.",
    "lines": [
        {"account_id": "A6200", "credit": "3000", "memo": "Move to prepaid"},
        {"account_id": "A6300", "debit": "3000", "memo": "Reclass placeholder"},
    ],
}


async def test_correction_is_posted_by_hand_and_proven_by_a_fresh_source(
    pod: AsyncClient, entity: LegalEntity, fpa_snapshot: dict[str, Any]
) -> None:
    case = await _open(pod, fpa_snapshot)
    # Unbalanced or for an old period: refused
    unbalanced = copy.deepcopy(CORRECTION)
    unbalanced["lines"][1]["debit"] = "2500"
    assert (await act(pod, case, "propose_correction", **unbalanced)).status_code == 422
    assert (
        await act(pod, case, "propose_correction", **(CORRECTION | {"period": "2026-08"}))
    ).status_code == 422

    case = (await act(pod, case, "propose_correction", **CORRECTION)).json()
    assert case["state"]["corrections"][0]["id"] == "C1"
    case = (
        await act(
            pod,
            case,
            "set_commentary",
            highlights=[{"text": "Cloud costs overstated.", "fact_ids": ["cost_driver.A6200"]}],
        )
    ).json()
    case = (await act(pod, case, "approve")).json()
    case = (await act(pod, case, "queue_correction", correction_id="C1")).json()
    (task,) = case["posting_tasks"]
    assert task["kind"] == "journal_entry" and task["reference"] == f"{case['reference']}-C1"
    assert case["status"] == "approved"  # queueing doesn't change what was signed off

    # The Finance Admin posts JE-900 in QuickBooks and records it
    r = await pod.post(
        f"/api/v1/pod/tasks/{task['id']}/actions",
        json={"action": "record", "expected_version": task["version"], "external_txn_id": "JE-900"},
    )
    assert r.status_code == 200, r.text
    task = r.json()

    # A fresh export: the journal's lines and the GL change they cause
    fresh = fpa_document(source_reference="export after JE-900", as_of="2026-10-06")
    for g in fresh["gl_lines"]:
        if g["id"] == "GL-A6200-2026-09":
            g["amount"] = "20000"
            g["transaction_ids"].append("JE-900:1")
        if g["id"] == "GL-A6300-2026-09":
            g["amount"] = "20000"
            g["transaction_ids"].append("JE-900:2")
    for n, (account, amount) in enumerate((("A6200", "-3000"), ("A6300", "3000")), start=1):
        fresh["transactions"].append(
            {
                "id": f"JE-900:{n}",
                "date": "2026-09-30",
                "period": "2026-09",
                "type": "JournalEntry",
                "counterparty": "Reclass",
                "account_id": account,
                "amount": amount,
                "status": "Posted",
                "gl_line_id": f"GL-{account}-2026-09",
                "document_ref": "JE-900",
            }
        )
    snap = (await import_snapshot(pod, entity, fresh)).json()["snapshot"]
    r = await pod.post(
        f"/api/v1/pod/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": snap["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"

    # Can't complete on the old figures: recalculate on the source that proves it
    case = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    assert case["allowed_actions"]["complete"] is not None
    assert "refresh" in case["completion_blockers"][0]
    case = (await act(pod, case, "refresh_source", snapshot_id=snap["id"])).json()
    assert case["status"] == "draft"
    cloud = next(
        d for d in case["state"]["changes"][-1]["cost_drivers"] if d["account_id"] == "A6200"
    )
    assert cloud["change"] == "0"  # 23k - 3k = 20k, as in August
    assert case["state"].get("commentary") is None  # figures changed: write it again
    assert case["state"]["corrections"][0]["id"] == "C1"


async def test_wrong_posting_is_not_verified(
    pod: AsyncClient, entity: LegalEntity, fpa_snapshot: dict[str, Any]
) -> None:
    case = await _open(pod, fpa_snapshot)
    case = (await act(pod, case, "propose_correction", **CORRECTION)).json()
    case = (
        await act(
            pod,
            case,
            "set_commentary",
            highlights=[{"text": "Cloud costs overstated.", "fact_ids": ["cost_driver.A6200"]}],
        )
    ).json()
    case = (await act(pod, case, "approve")).json()
    case = (await act(pod, case, "queue_correction", correction_id="C1")).json()
    task = case["posting_tasks"][0]
    task = (
        await pod.post(
            f"/api/v1/pod/tasks/{task['id']}/actions",
            json={
                "action": "record",
                "expected_version": task["version"],
                "external_txn_id": "JE-901",
            },
        )
    ).json()
    fresh = fpa_document(source_reference="export with a wrong JE", as_of="2026-10-06")
    fresh["transactions"].append(
        {
            "id": "JE-901",
            "date": "2026-09-30",
            "period": "2026-09",
            "type": "JournalEntry",
            "account_id": "A6200",
            "amount": "-2000",  # posted 2,000 instead of 3,000, and no GL change
            "status": "Posted",
        }
    )
    snap = (await import_snapshot(pod, entity, fresh)).json()["snapshot"]
    r = await pod.post(
        f"/api/v1/pod/tasks/{task['id']}/actions",
        json={"action": "verify", "expected_version": task["version"], "snapshot_id": snap["id"]},
    )
    assert r.status_code in (409, 422), r.text
    assert "Cloud and tools" in json.dumps(r.json())


def test_numbers_in_words_count_as_stating_a_figure() -> None:
    from src.app.service_pod.common.ai import states_number

    assert states_number("Margin rose by one point seven percentage points")
    assert states_number("Revenue grew by sixty thousand dollars")
    assert states_number("Up 12%")
    assert not states_number("Confirm whether the new revenue is one-time or recurring")
    assert not states_number("Subcontractor costs rose, partly offsetting the revenue gain")


async def test_a_rejected_draft_is_retried_once_with_the_reason(
    pod: AsyncClient,
    fpa_snapshot: dict[str, Any],
    fake_llm: FakeLLM,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _open(pod, fpa_snapshot)
    bad = copy.deepcopy(COMMENTARY)
    bad["highlights"][0]["text"] = "Revenue rose by sixty thousand dollars."
    outputs = [bad, COMMENTARY]
    original = fake_llm.generate_structured

    async def in_turn(**kw: Any) -> Any:
        fake_llm.output = outputs.pop(0)
        return await original(**kw)

    monkeypatch.setattr(fake_llm, "generate_structured", in_turn)
    r = await _commentary(pod, case)
    assert r.status_code == 200, r.text
    assert "previous draft was rejected" in fake_llm.calls[1][1]
    assert "sixty thousand" in fake_llm.calls[1][1]


async def test_commentary_is_short(
    pod: AsyncClient, fpa_snapshot: dict[str, Any], fake_llm: FakeLLM
) -> None:
    case = await _open(pod, fpa_snapshot)
    long = copy.deepcopy(COMMENTARY)
    long["highlights"] = long["highlights"] * 3  # six findings: more than four
    fake_llm.output = long
    r = await _commentary(pod, case)
    assert r.status_code == 422
    assert "more than 4 highlights" in r.json()["detail"]["message"]


def test_facts_skip_what_did_not_move() -> None:
    from src.app.service_pod.common.canonical import plain
    from src.app.service_pod.flows.fpa_trend.service import facts

    ids = {f.id for f in facts(plain(compute(_doc(), FULL)))}
    assert {"revenue.2026-04", "revenue.2026-09", "trend.revenue", "trend.margin"} <= ids
    assert "revenue_driver.4" not in ids  # Harbor didn't move: not a driver to explain
