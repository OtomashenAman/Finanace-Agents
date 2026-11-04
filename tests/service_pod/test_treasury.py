"""Treasury Forecast (TDD section 9): bank-verified opening cash, AR promises reviewed tranche
by tranche, the 91-day forecast, scenarios, mitigation and the two sign-offs."""

import copy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from src.app.entities.models import LegalEntity
from src.app.service_pod.core.cases.exceptions import CaseSelectionError
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.flows.treasury.engine import (
    apply_shifts,
    forecast,
    opening_cash,
)
from tests.service_pod.conftest import act, import_snapshot

START = date(2026, 11, 5)
RECEIPTS = [
    {
        "id": "R1",
        "date": "2026-11-08",
        "amount": Decimal(50000),
        "probability": Decimal(1),
        "expected": Decimal(50000),
    },
    {
        "id": "R2",
        "date": "2026-11-22",
        "amount": Decimal(40000),
        "probability": Decimal(1),
        "expected": Decimal(40000),
    },
    {
        "id": "R3",
        "date": "2026-11-25",
        "amount": Decimal(60000),
        "probability": Decimal(1),
        "expected": Decimal(60000),
    },
]
OUTFLOWS = [
    {"id": "O1", "date": "2026-11-15", "amount": Decimal(180000)},
    {"id": "O2", "date": "2026-11-25", "amount": Decimal(120000)},
]


def treasury_document(**changes: Any) -> dict[str, Any]:
    """The deck's Treasury example: 250k cleared cash, 125k buffer, 300k approved outflows
    (and one unapproved), Cobalt's INV-401 (90k) and INV-402 (60k)."""
    doc: dict[str, Any] = {
        "provenance": "QUICKBOOKS_READONLY_EXPORT",
        "company_id": "QB-ESOL-1",
        "company_name": "E-Solutions Inc",
        "entity": "US01",
        "currency": "USD",
        "basis": "Accrual",
        "as_of": "2026-11-05",
        "source_reference": "treasury export",
        "customers": [
            {"id": "C2", "name": "Cobalt Systems", "email": "pay@cobalt.example"},
        ],
        "invoices": [
            {
                "id": "I401",
                "number": "INV-401",
                "customer_id": "C2",
                "txn_date": "2026-10-09",
                "due_date": "2026-10-20",
                "original_amount": "90000",
                "balance": "90000",
            },
            {
                "id": "I402",
                "number": "INV-402",
                "customer_id": "C2",
                "txn_date": "2026-10-26",
                "due_date": "2026-11-01",
                "original_amount": "60000",
                "balance": "60000",
            },
        ],
        "payments": [],
        "cash_position": {
            "as_of": "2026-11-05",
            "bank_balance": "250000",
            "quickbooks_cash_balance": "250000",
            "reconciliation_balance": "250000",
            "policy_buffer": "125000",
            "cleared": True,
            "proof_reference": "Bank statement 2026-11-05",
        },
        "planned_outflows": [
            {
                "id": "O1",
                "date": "2026-11-15",
                "amount": "180000",
                "category": "Payroll",
                "approved": True,
            },
            {
                "id": "O2",
                "date": "2026-11-25",
                "amount": "120000",
                "category": "Suppliers",
                "approved": True,
            },
            {
                "id": "O3",
                "date": "2026-12-10",
                "amount": "40000",
                "category": "Fit-out",
                "approved": False,
            },
        ],
    }
    doc.update(changes)
    return doc


# --- the engine ------------------------------------------------------------------------


def test_deck_base_forecast() -> None:
    f = forecast(START, Decimal(250000), Decimal(125000), RECEIPTS, OUTFLOWS)
    assert (len(f["days"]), len(f["weeks"])) == (91, 13)
    assert f["ending_cash"] == Decimal(100000)  # 250k + 150k - 300k
    assert f["ending_shortfall"] == Decimal(25000)
    # 250k + 50k - 180k = 120k on 15 Nov: below the buffer before the end, too
    assert f["first_breach"] == date(2026, 11, 15)
    assert f["max_shortfall"] == Decimal(25000)
    week2 = f["weeks"][1]
    assert (week2["outflow"], week2["minimum_cash"]) == (Decimal(180000), Decimal(120000))


def test_scenarios_need_shifts_across_the_horizon() -> None:
    # Optimistic: 55k of the supplier run moves past the 91 days -> 155k
    r, o = apply_shifts(
        RECEIPTS,
        OUTFLOWS,
        [{"id": "S1", "event_id": "O2", "amount": "55000", "to_date": "2027-02-10"}],
    )
    assert forecast(START, Decimal(250000), Decimal(125000), r, o)["ending_cash"] == Decimal(155000)
    # Stress: 55k of the receipts arrive after the horizon -> 45k
    r, o = apply_shifts(
        RECEIPTS,
        OUTFLOWS,
        [{"id": "S2", "event_id": "R3", "amount": "55000", "to_date": "2027-02-20"}],
    )
    assert forecast(START, Decimal(250000), Decimal(125000), r, o)["ending_cash"] == Decimal(45000)
    # Moving a date within the horizon changes the timing, never the total
    r, o = apply_shifts(
        RECEIPTS,
        OUTFLOWS,
        [{"id": "S3", "event_id": "R1", "amount": "50000", "to_date": "2026-12-20"}],
    )
    moved = forecast(START, Decimal(250000), Decimal(125000), r, o)
    assert moved["ending_cash"] == Decimal(100000)
    assert moved["max_shortfall"] == Decimal(75000)  # 25 Nov: 110k + 60k - 120k = 50k


def test_expected_receipts_carry_their_probability() -> None:
    risky = [dict(RECEIPTS[0], probability=Decimal("0.5"), expected=Decimal(25000))]
    f = forecast(START, Decimal(250000), Decimal(125000), risky, [])
    assert f["ending_cash"] == Decimal(275000)


def test_opening_cash_must_be_cleared_dated_and_reconciled() -> None:
    doc = treasury_document()
    doc["cash_position"]["reconciliation_balance"] = None
    with pytest.raises(CaseSelectionError, match="never taken from the cash balance"):
        opening_cash(SnapshotDocument.model_validate(doc))
    doc = treasury_document()
    doc["cash_position"] |= {
        "cleared": False,
        "as_of": "2026-11-04",
        "quickbooks_cash_balance": "249000",
    }
    _, issues = opening_cash(SnapshotDocument.model_validate(doc))
    assert sorted(i["code"] for i in issues) == [
        "cash_date",
        "cash_not_cleared",
        "cash_vs_quickbooks",
    ]


# --- the case flow ---------------------------------------------------------------------


@pytest.fixture
async def treasury_snapshot(pod: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(pod, entity, treasury_document())
    assert r.status_code == 201, r.text
    return r.json()["snapshot"]  # type: ignore[no-any-return]


async def _promises(pod: AsyncClient, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Cobalt's approved payment schedule in AR Collections (the deck's three tranches)."""
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "ar_collections",
            "snapshot_id": snapshot["id"],
            "title": "Cobalt Systems",
            "selection": {"customer_id": "C2", "invoice_ids": ["I401", "I402"]},
        },
    )
    assert r.status_code == 201, r.text
    case = r.json()
    for invoice, amount, when in (
        ("I401", "50000", "2026-11-08"),
        ("I401", "40000", "2026-11-22"),
        ("I402", "60000", "2026-11-25"),
    ):
        case = (
            await act(
                pod,
                case,
                "propose_commitment",
                invoice_id=invoice,
                amount=amount,
                expected_date=when,
            )
        ).json()
        r = await act(
            pod,
            case,
            "decide_commitment",
            commitment_id=case["commitments"][-1]["id"],
            decision="approved",
        )
        assert r.status_code == 200, r.text
        case = r.json()
    return case


async def _open(pod: AsyncClient, snapshot: dict[str, Any]) -> dict[str, Any]:
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "treasury",
            "snapshot_id": snapshot["id"],
            "title": "13 weeks from 5 Nov",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def _review_all(pod: AsyncClient, case: dict[str, Any]) -> dict[str, Any]:
    for receipt in case["state"]["receipts"]:
        case = (
            await act(pod, case, "review_receipt", receipt_id=receipt["id"], include=True)
        ).json()
    return case


async def test_forecast_from_promises_to_cfo_approval(
    pod: AsyncClient, treasury_snapshot: dict[str, Any]
) -> None:
    await _promises(pod, treasury_snapshot)
    case = await _open(pod, treasury_snapshot)
    receipts = case["state"]["receipts"]
    assert [(r["invoice_number"], r["amount"], r["date"]) for r in receipts] == [
        ("INV-401", "50000", "2026-11-08"),
        ("INV-401", "40000", "2026-11-22"),
        ("INV-402", "60000", "2026-11-25"),
    ]
    assert case["stage"] == "receipts"
    assert any("Review 3 imported receipt tranches" in b for b in case["blockers"])

    # A probability below certainty needs a reason
    r = await act(
        pod, case, "review_receipt", receipt_id=receipts[2]["id"], include=True, probability="0.8"
    )
    assert r.status_code == 422
    case = await _review_all(pod, case)
    base = case["state"]["results"]["base"]
    assert (base["ending_cash"], base["first_breach"], base["max_shortfall"]) == (
        "100000",
        "2026-11-15",
        "25000",
    )
    assert case["stage"] == "forecast"

    # A breach anywhere needs an owned mitigation before any sign-off
    assert any("owned mitigation" in b for b in case["blockers"])
    assert (await act(pod, case, "approve")).status_code == 409
    me = case["owner"]["id"]
    case = (
        await act(
            pod,
            case,
            "add_action",
            title="Delay discretionary spend; escalate Cobalt INV-402",
            owner_id=me,
            due_date="2026-11-12",
        )
    ).json()
    case = (await act(pod, case, "approve")).json()
    assert [a["capacity"] for a in case["approvals"]] == ["Treasury Head"]
    assert (case["status"], case["next_signoff"], case["stage"]) == ("draft", "CFO", "cfo")
    case = (await act(pod, case, "approve")).json()
    assert [a["capacity"] for a in case["approvals"]] == ["Treasury Head", "CFO"]
    assert case["status"] == "approved"

    csv = await pod.get(f"/api/v1/pod/treasury/cases/{case['id']}/forecast.csv")
    assert csv.status_code == 200
    assert csv.text.count("\nbase,") == 91 and "2026-11-15" in csv.text


async def test_scenario_shifts_are_bounded_and_explained(
    pod: AsyncClient, treasury_snapshot: dict[str, Any]
) -> None:
    await _promises(pod, treasury_snapshot)
    case = await _review_all(pod, await _open(pod, treasury_snapshot))
    shift = {"scenario": "optimistic", "event_id": "O2", "to_date": "2027-02-10"}
    note = "Supplier agreed to move part of the November run into February."
    assert (
        await act(pod, case, "add_shift", amount="130000", note=note, **shift)
    ).status_code == 422
    assert (
        await act(pod, case, "add_shift", amount="55000", note="later", **shift)
    ).status_code == 422
    case = (await act(pod, case, "add_shift", amount="55000", note=note, **shift)).json()
    stress_receipt = case["state"]["receipts"][2]["id"]
    case = (
        await act(
            pod,
            case,
            "add_shift",
            scenario="stress",
            event_id=stress_receipt,
            amount="55000",
            to_date="2027-02-20",
            note="Cobalt may hold INV-402 until the timesheets are approved.",
        )
    ).json()
    results = case["state"]["results"]
    assert (
        results["base"]["ending_cash"],
        results["optimistic"]["ending_cash"],
        results["stress"]["ending_cash"],
    ) == (
        "100000",
        "155000",
        "45000",
    )
    shift_id = case["state"]["scenarios"]["optimistic"][0]["id"]
    case = (await act(pod, case, "remove_shift", scenario="optimistic", shift_id=shift_id)).json()
    assert case["state"]["results"]["optimistic"]["ending_cash"] == "100000"


async def test_schedules_beyond_the_refreshed_balance_are_rejected(
    pod: AsyncClient, entity: LegalEntity, treasury_snapshot: dict[str, Any]
) -> None:
    await _promises(pod, treasury_snapshot)
    case = await _review_all(pod, await _open(pod, treasury_snapshot))
    # A newer export: Cobalt paid 50k of INV-401 (balance 40k), so 50k + 40k promised is too much
    doc = treasury_document(source_reference="re-export", as_of="2026-11-05")
    doc["invoices"][0]["balance"] = "40000"
    doc["cash_position"] = copy.deepcopy(doc["cash_position"])
    newer = (await import_snapshot(pod, entity, doc)).json()["snapshot"]
    case = (await act(pod, case, "refresh_source", snapshot_id=newer["id"])).json()
    rejected = [r for r in case["state"]["receipts"] if r["rejected"]]
    assert [r["invoice_number"] for r in rejected] == ["INV-401", "INV-401"]
    assert "exceed its refreshed balance" in rejected[0]["rejected"]
    kept = [r for r in case["state"]["receipts"] if not r["rejected"]]
    assert kept[0]["review"]["include"] is True  # the unchanged tranche keeps its review


async def test_sources_screen(pod: AsyncClient, treasury_snapshot: dict[str, Any]) -> None:
    await _promises(pod, treasury_snapshot)
    body = (await pod.get("/api/v1/pod/treasury/sources")).json()
    source = next(s for s in body["sources"] if s["snapshot"]["id"] == treasury_snapshot["id"])
    assert (source["opening_cash"], source["policy_buffer"], source["approved_outflows"]) == (
        "250000",
        "125000",
        "300000",
    )
    assert source["checks"] == [] and source["commitments"] == 3
