from datetime import timedelta
from typing import Any

from httpx import AsyncClient

from src.app.common.clock import utcnow
from tests.conftest import FakeLLM
from tests.service_pod.conftest import act, customer_replies, open_ar_case


async def _dashboard(pod: AsyncClient) -> dict[str, Any]:
    r = await pod.get("/api/v1/pod/dashboard")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_cases_are_counted_by_where_they_stand(
    pod: AsyncClient, snapshot: dict[str, Any], fake_llm: FakeLLM
) -> None:
    await open_ar_case(pod, snapshot, ("I101",))  # nothing sent yet
    answered = await customer_replies(pod, await open_ar_case(pod, snapshot, ("I102",)), fake_llm)

    d = await _dashboard(pod)
    assert d["open_cases"] == 2
    assert d["phases"]["compose"] == 1
    # The answered case is ready exactly when the case page would offer Approve
    ready = answered["allowed_actions"]["approve"] is None
    assert d["phases"]["ready" if ready else "review"] == 1
    assert d["aging"][0] == {"label": "0-7 days", "count": 2}
    assert sorted(c["phase"] for c in d["open"]) == sorted(
        ["compose", "ready" if ready else "review"]
    )
    assert d["email"]["sent_30d"] == 1
    assert d["email"]["replies_30d"] == 1


async def test_promises_due_and_overdue(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    today = utcnow().date()
    case = ar_case
    for invoice, amount, when in (
        ("I101", "6000", today + timedelta(days=3)),
        ("I102", "2500", today - timedelta(days=2)),
    ):
        r = await act(
            pod,
            case,
            "propose_commitment",
            invoice_id=invoice,
            amount=amount,
            expected_date=str(when),
        )
        assert r.status_code == 200, r.text
        case = r.json()
        r = await act(
            pod,
            case,
            "decide_commitment",
            commitment_id=case["commitments"][-1]["id"],
            decision="approved",
        )
        assert r.status_code == 200, r.text
        case = r.json()

    d = await _dashboard(pod)
    assert d["promised"] == [{"currency": "USD", "amount": "8500.00"}]
    assert [p["invoice_number"] for p in d["due_this_week"]] == ["INV-101"]
    assert [p["invoice_number"] for p in d["overdue_promises"]] == ["INV-102"]


async def test_messages_carry_their_case_reference(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    await customer_replies(pod, ar_case, fake_llm)
    messages = (await pod.get("/api/v1/pod/messages")).json()
    assert {m["case_reference"] for m in messages} == {ar_case["reference"]}
