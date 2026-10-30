"""After the schedule: watching promises (TDD 6 "monitor follow-up actions") and the AR case
linked to the bank case of the same customer."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from src.app.common import clock
from src.app.entities.models import LegalEntity
from tests.service_pod.conftest import act, import_snapshot, snapshot_payload

RECEIPT = {
    "reference": "WIRE-2901",
    "payer": "Harbor Distribution",
    "date": "2026-11-05",
    "amount": "9000",
    "currency": "USD",
    "cleared": True,
}


@pytest.fixture
async def snap(pod: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(pod, entity, snapshot_payload(bank_receipts=[RECEIPT]))
    return r.json()["snapshot"]  # type: ignore[no-any-return]


async def _ar_case(pod: AsyncClient, snap: dict[str, Any]) -> dict[str, Any]:
    case = (
        await pod.post(
            "/api/v1/pod/cases",
            json={
                "workflow": "ar_collections",
                "snapshot_id": snap["id"],
                "title": "Harbor",
                "selection": {"customer_id": "C1", "invoice_ids": ["I101", "I102"]},
            },
        )
    ).json()
    for invoice, amount, when in (
        ("I101", "6000", "2026-11-08"),
        ("I101", "9000", "2026-11-20"),
        ("I102", "10000", "2026-11-11"),
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
    for c in case["commitments"]:
        case = (
            await act(pod, case, "decide_commitment", commitment_id=c["id"], decision="approved")
        ).json()
    return case


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 11, 10, 9, tzinfo=UTC))


async def test_promises_are_watched_until_cash_shows(
    pod: AsyncClient, snap: dict[str, Any], entity: LegalEntity
) -> None:
    case = await _ar_case(pod, snap)
    p = (await pod.get("/api/v1/pod/ar/portfolio")).json()
    states = [
        (r["invoice_number"], r["amount"], r["state"], r["days_until"]) for r in p["promises"]
    ]
    assert states == [
        ("INV-101", "6000.00", "overdue", -2),
        ("INV-102", "10000.00", "due", 1),
        ("INV-101", "9000.00", "upcoming", 10),
    ]
    harbor = next(c for c in p["customers"] if c["name"] == "Harbor Distribution")
    assert harbor["next_action"] == "Follow up on the missed promise"
    assert harbor["open_case"]["id"] == case["id"]

    # A newer export shows 6,000 paid on INV-101: that promise is kept, the others aren't yet
    fresh = snapshot_payload(bank_receipts=[RECEIPT], source_reference="later")
    fresh["invoices"][0]["balance"] = "9000.00"
    await import_snapshot(pod, entity, fresh)
    p = (await pod.get("/api/v1/pod/ar/portfolio")).json()
    kept = [r for r in p["promises"] if r["state"] == "received"]
    assert [(r["amount"], r["received_by"]) for r in kept] == [("6000.00", "a newer source")]
    harbor = next(c for c in p["customers"] if c["name"] == "Harbor Distribution")
    assert harbor["next_action"] != "Follow up on the missed promise"


async def test_ar_and_bank_cases_of_a_customer_are_linked(
    pod: AsyncClient, snap: dict[str, Any]
) -> None:
    ar_case = await _ar_case(pod, snap)
    bank_case = (
        await pod.post(
            "/api/v1/pod/cases",
            json={
                "workflow": "bank_recon",
                "snapshot_id": snap["id"],
                "title": "WIRE-2901",
                "selection": {"receipt_reference": "WIRE-2901", "customer_id": "C1"},
            },
        )
    ).json()

    # Worklists know the step each case is on
    listed = (await pod.get("/api/v1/pod/cases")).json()
    assert {c["reference"]: c["stage"] for c in listed} == {
        ar_case["reference"]: "email",
        bank_case["reference"]: "request",
    }

    (related,) = bank_case["related_cases"]
    assert related["reference"] == ar_case["reference"]
    assert related["summary"] == (
        "INV-101, INV-102 · open USD 25,000.00 · approved promises USD 25,000.00"
    )
    ar = (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).json()
    (related,) = ar["related_cases"]
    assert related["reference"] == bank_case["reference"]
    assert related["summary"] == "WIRE-2901 USD 9,000.00 · waiting for the customer's allocation"
