"""Bank-to-Invoice end to end with the deck's WIRE-2901 example (slides 15-18, TDD 7)."""

from typing import Any

import pytest
from httpx import AsyncClient

from src.app.entities.models import LegalEntity
from tests.conftest import FakeLLM
from tests.service_pod.conftest import (
    CUSTOMER_EMAIL,
    act,
    import_snapshot,
    snapshot_payload,
)

CHECKS = {"recipient": True, "mapping": True, "tone": True}
RECEIPTS = [
    {
        "reference": "WIRE-2901",
        "payer": "Harbor Distribution Inc.",
        "date": "2026-11-05",
        "amount": "9000",
        "currency": "USD",
        "cleared": True,
    },
    {
        "reference": "WIRE-3000",
        "payer": "Harbor Distribution",
        "date": "2026-11-05",
        "amount": "500",
        "currency": "USD",
        "cleared": False,
    },
    {
        "reference": "WIRE-3100",
        "payer": "HDI Holdings",
        "date": "2026-11-05",
        "amount": "700",
        "currency": "USD",
        "cleared": True,
    },
]
REPLY_A = "Apply $6,000 to INV-101 and $3,000 to INV-102."


def books(**changes: Any) -> dict[str, Any]:
    return snapshot_payload(bank_receipts=RECEIPTS, **changes)


@pytest.fixture
async def snap(pod: AsyncClient, entity: LegalEntity) -> dict[str, Any]:
    r = await import_snapshot(pod, entity, books())
    assert r.status_code == 201, r.text
    return r.json()["snapshot"]  # type: ignore[no-any-return]


async def _open(pod: AsyncClient, snap: dict[str, Any], **selection: Any) -> Any:
    return await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "bank_recon",
            "snapshot_id": snap["id"],
            "title": "WIRE",
            "selection": {"receipt_reference": "WIRE-2901", "customer_id": "C1", **selection},
        },
    )


async def _message(pod: AsyncClient, llm: FakeLLM, case: dict[str, Any], purpose: str) -> Any:
    llm.output = {"opening": "Dear Harbor AP,", "closing": "Thank you,"}
    draft = (
        await pod.post(
            f"/api/v1/pod/cases/{case['id']}/messages/compose", json={"purpose": purpose}
        )
    ).json()
    if "detail" in draft:
        return draft
    return await pod.post(
        f"/api/v1/pod/cases/{case['id']}/messages",
        json={
            "audience": "customer",
            "purpose": purpose,
            "to_email": CUSTOMER_EMAIL,
            "subject": draft["subject"],
            "body": draft["body"],
        },
    )


async def _send(pod: AsyncClient, msg: dict[str, Any]) -> dict[str, Any]:
    r = await pod.post(
        f"/api/v1/pod/messages/{msg['id']}/send",
        json={"expected_version": msg["version"], "checks": CHECKS},
    )
    return r.json()  # type: ignore[no-any-return]


async def _reply(
    pod: AsyncClient,
    llm: FakeLLM,
    case: dict[str, Any],
    sent: dict[str, Any],
    text: str,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    llm.output = {"allocations": lines, "document_requests": [], "unclear": []}
    r = await pod.post(
        f"/api/v1/pod/cases/{case['id']}/replies",
        json={"from_email": CUSTOMER_EMAIL, "body": text, "reply_to_message_id": sent["id"]},
    )
    assert r.status_code == 201, r.text
    return (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()  # type: ignore[no-any-return]


def line(number: str, amount: str, quote: str) -> dict[str, Any]:
    return {"invoice_number": number, "amount": amount, "quote": quote, "confidence": 0.95}


async def test_only_cleared_unrecorded_receipts_of_a_verified_payer(
    pod: AsyncClient, snap: dict[str, Any], fake_llm: FakeLLM, entity: LegalEntity
) -> None:
    r = await _open(pod, snap, receipt_reference="WIRE-3000")
    assert "cleared" in r.json()["detail"]["message"]
    r = await _open(pod, snap, receipt_reference="WIRE-3100")
    assert "payer_confirmation" in r.json()["detail"]["message"]
    r = await _open(
        pod,
        snap,
        receipt_reference="WIRE-3100",
        payer_confirmation="Remittance names Harbor as the customer",
    )
    assert r.status_code == 201

    assert (await _open(pod, snap)).status_code == 201  # "Inc." is the same company
    r = await _open(pod, snap)
    assert "Another open case" in r.json()["detail"]["message"]


async def test_allocation_posting_and_verification(
    pod: AsyncClient, snap: dict[str, Any], fake_llm: FakeLLM, entity: LegalEntity
) -> None:
    case = (await _open(pod, snap)).json()
    assert any("No customer allocation" in b for b in case["blockers"])

    ack = await _message(pod, fake_llm, case, "acknowledgement")
    assert ack["detail"]["code"] == "message_refused"  # only after verification

    request = (await _message(pod, fake_llm, case, "allocation_request")).json()
    assert "WIRE-2901, USD 9,000.00 on 2026-11-05" in request["fact_block"]
    sent = await _send(pod, request)

    case = await _reply(
        pod,
        fake_llm,
        case,
        sent,
        REPLY_A,
        [
            line("INV-101", "6000", "Apply $6,000 to INV-101"),
            line("INV-102", "3000", "$3,000 to INV-102"),
        ],
    )
    assert [(x["invoice_number"], x["amount"]) for x in case["state"]["allocation"]["lines"]] == [
        ("INV-101", "6000"),
        ("INV-102", "3000"),
    ]
    assert case["blockers"] == []
    case = (await act(pod, case, "approve")).json()
    case = (await act(pod, case, "create_posting_task")).json()
    (task,) = case["posting_tasks"]
    assert task["instructions"]["balances_after"] == {"INV-101": "9000", "INV-102": "7000"}
    assert (await act(pod, case, "create_posting_task")).status_code == 409  # once

    async def task_action(action: str, **body: Any) -> Any:
        nonlocal task
        r = await pod.post(
            f"/api/v1/pod/tasks/{task['id']}/actions",
            json={"action": action, "expected_version": task["version"], **body},
        )
        if r.status_code == 200:
            task = r.json()
        return r

    await task_action("record", external_txn_id="PMT-77")

    def posted(
        allocs: list[tuple[str, str]], balances: tuple[str, str], ref: str
    ) -> dict[str, Any]:
        fresh = books(source_reference=ref)
        fresh["payments"] = [
            {
                "id": "PMT-77",
                "customer_id": "C1",
                "date": "2026-11-05",
                "amount": "9000",
                "currency": "USD",
                "reference": "WIRE-2901",
                "allocations": [{"invoice_id": i, "amount": a} for i, a in allocs],
            }
        ]
        fresh["invoices"][0]["balance"], fresh["invoices"][1]["balance"] = balances
        return fresh

    wrong = (
        await import_snapshot(pod, entity, posted([("I101", "9000")], ("6000", "10000"), "e2"))
    ).json()
    r = await task_action("verify", snapshot_id=wrong["snapshot"]["id"])
    assert r.status_code == 409
    assert "exactly as approved" in r.json()["detail"]["message"]

    right = (
        await import_snapshot(
            pod, entity, posted([("I101", "6000"), ("I102", "3000")], ("9000", "7000"), "e3")
        )
    ).json()
    r = await task_action("verify", snapshot_id=right["snapshot"]["id"])
    assert r.status_code == 200, r.text
    assert task["status"] == "verified"

    case = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    ack = (await _message(pod, fake_llm, case, "acknowledgement")).json()
    assert "INV-101  USD 6,000.00" in ack["fact_block"]
    assert (await act(pod, case, "complete")).json()["status"] == "completed"


async def test_allocation_must_settle_the_receipt(
    pod: AsyncClient, snap: dict[str, Any], fake_llm: FakeLLM
) -> None:
    case = (await _open(pod, snap)).json()
    sent = await _send(pod, (await _message(pod, fake_llm, case, "allocation_request")).json())
    text = "Please put $5,000 on INV-101."
    case = await _reply(pod, fake_llm, case, sent, text, [line("INV-101", "5000", text)])
    assert any("receipt is 9000" in b for b in case["blockers"])
    assert case["review_tasks"][0]["kind"] == "ambiguity"

    # Recorded by hand from the customer's words, it still has to add up
    reply_id = case["messages"][-1]["id"]
    r = await act(
        pod,
        case,
        "set_allocation",
        lines=[{"invoice_id": "I101", "amount": "9000"}],
        source_message_id=reply_id,
        quote=text,
    )
    assert r.status_code == 409  # 9000 isn't in the quoted words


async def test_worklist(pod: AsyncClient, snap: dict[str, Any], fake_llm: FakeLLM) -> None:
    await _open(pod, snap)
    r = await pod.get("/api/v1/pod/bank/unapplied")
    assert r.status_code == 200, r.text
    w = r.json()
    rows = {row["reference"]: row for row in w["rows"]}
    assert set(rows) == {"WIRE-2901", "WIRE-3000", "WIRE-3100"}
    assert rows["WIRE-2901"]["matched_customer"] == "Harbor Distribution"
    assert rows["WIRE-2901"]["open_case"] is not None
    assert rows["WIRE-3100"]["matched_customer"] is None
    assert rows["WIRE-3000"]["cleared"] is False
    assert w["unmatched_total"] in ("9700", "9700.00")
