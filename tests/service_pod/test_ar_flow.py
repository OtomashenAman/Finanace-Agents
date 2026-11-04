"""AR Collections end to end with the deck's reply examples (slide 10, TDD section 6). The
AI is a fake returning what a model would; every rule after it is the real code."""

from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient

from src.app.core.llm.base import LLMNotConfiguredError
from src.app.entities.models import LegalEntity
from tests.conftest import FakeLLM
from tests.service_pod.conftest import CUSTOMER_EMAIL, act, import_snapshot, snapshot_payload

CHECKS = {"recipient": True, "mapping": True, "tone": True}
WORDING = {"opening": "Dear Harbor AP,\n\nPlease confirm your payment plan.", "closing": "Regards,"}


def tranche(number: str, amount: str, date: str | None, quote: str, **kw: Any) -> dict[str, Any]:
    return {
        "invoice_number": number,
        "amount": amount,
        "date": date,
        "quote": quote,
        "inferred": kw.get("inferred", False),
        "confidence": kw.get("confidence", 0.95),
    }


def read(**parts: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "intent": "reply",
        "tranches": [],
        "disputes": [],
        "document_requests": [],
        "unclear": [],
    }
    return {**base, **parts}


async def _case(client: AsyncClient, case_id: str) -> dict[str, Any]:
    r = await client.get(f"/api/v1/pod/cases/{case_id}")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _send_request(pod: AsyncClient, case: dict[str, Any], llm: FakeLLM) -> dict[str, Any]:
    llm.output = WORDING
    r = await pod.post(
        f"/api/v1/pod/cases/{case['id']}/messages/compose",
        json={"purpose": "payment_schedule_request"},
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["ai_drafted"] is True
    msg = (
        await pod.post(
            f"/api/v1/pod/cases/{case['id']}/messages",
            json={
                "audience": "customer",
                "purpose": "payment_schedule_request",
                "to_email": draft["to_email"],
                "subject": draft["subject"],
                "body": draft["body"],
            },
        )
    ).json()
    assert msg["fact_block"] == draft["fact_block"]
    msg = (
        await pod.post(
            f"/api/v1/pod/messages/{msg['id']}/send",
            json={"expected_version": msg["version"], "checks": CHECKS},
        )
    ).json()
    assert msg["status"] == "sent"
    return msg  # type: ignore[no-any-return]


async def _reply(
    pod: AsyncClient,
    case: dict[str, Any],
    sent: dict[str, Any],
    text: str,
    llm: FakeLLM,
    output: dict[str, Any],
) -> dict[str, Any]:
    llm.output = output
    r = await pod.post(
        f"/api/v1/pod/cases/{case['id']}/replies",
        json={"from_email": CUSTOMER_EMAIL, "body": text, "reply_to_message_id": sent["id"]},
    )
    assert r.status_code == 201, r.text
    return await _case(pod, case["id"])


async def test_selection_is_checked(pod: AsyncClient, snapshot: dict[str, Any]) -> None:
    r = await pod.post(
        "/api/v1/pod/cases",
        json={
            "workflow": "ar_collections",
            "snapshot_id": snapshot["id"],
            "title": "x",
            "selection": {"customer_id": "C2", "invoice_ids": ["I101"]},
        },
    )
    assert r.status_code == 422
    assert "isn't one of Cobalt" in r.json()["detail"]["message"]


async def test_fact_block_is_locked(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    fake_llm.output = {"opening": "Dear AP, you owe $25,000.", "closing": "Bye"}
    r = await pod.post(
        f"/api/v1/pod/cases/{ar_case['id']}/messages/compose",
        json={"purpose": "payment_schedule_request"},
    )
    draft = r.json()
    assert draft["ai_drafted"] is False  # the AI wrote a figure itself: template instead
    assert "INV-101" in draft["fact_block"] and "USD 15,000.00" in draft["fact_block"]
    assert "Total open: USD 25,000.00" in draft["body"]

    body = {
        "audience": "customer",
        "purpose": "payment_schedule_request",
        "to_email": CUSTOMER_EMAIL,
        "subject": "s",
        "body": "Please pay what you owe.",
    }
    r = await pod.post(f"/api/v1/pod/cases/{ar_case['id']}/messages", json=body)
    assert r.status_code == 409  # the verified figures were left out
    assert "verified figures" in r.json()["detail"]["message"]

    r = await pod.post(
        f"/api/v1/pod/cases/{ar_case['id']}/messages", json={**body, "body": draft["body"]}
    )
    msg = r.json()
    r = await pod.patch(
        f"/api/v1/pod/messages/{msg['id']}",
        json={"expected_version": msg["version"], "body": draft["body"].replace("15,000", "1,500")},
    )
    assert r.status_code == 409  # a figure can't be edited


async def test_email_states_terms_and_agreement(
    pod: AsyncClient, entity: LegalEntity, fake_llm: FakeLLM
) -> None:
    payload = snapshot_payload(source_reference="with terms")
    payload["invoices"][0]["terms"] = "Net 30"
    payload["contracts"] = [
        {
            "id": "MSA-HARBOR",
            "customer_id": "C1",
            "invoice_ids": ["I101", "I102"],
            "terms": "Net 30 from invoice date",
            "status": "Active",
        }
    ]
    snap = (await import_snapshot(pod, entity, payload)).json()["snapshot"]
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
    assert case["state"]["contract"] == {"id": "MSA-HARBOR", "terms": "Net 30 from invoice date"}
    fake_llm.output = {"opening": "Dear AP,", "closing": "Thank you,"}
    draft = (
        await pod.post(
            f"/api/v1/pod/cases/{case['id']}/messages/compose",
            json={"purpose": "payment_schedule_request"},
        )
    ).json()
    facts = draft["fact_block"]
    assert "Terms" in facts and "Net 30" in facts
    assert "Agreement: MSA-HARBOR: Net 30 from invoice date" in facts
    assert facts in draft["body"]


async def test_reply_a_both_on_nov_12(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    text = "Pay both on Nov 12."
    case = await _reply(
        pod,
        ar_case,
        sent,
        text,
        fake_llm,
        read(
            tranches=[
                tranche("INV-101", "15000", "2026-11-12", text, inferred=True),
                tranche("INV-102", "10000", "2026-11-12", text, inferred=True),
            ]
        ),
    )
    reply = case["messages"][-1]
    assert reply["extraction_status"] == "done"
    assert reply["extraction"]["provenance"]["prompt_version"] == "ar_reply/v2"
    assert [
        (c["invoice_number"], c["amount"], c["expected_date"]) for c in case["commitments"]
    ] == [
        ("INV-101", "15000.00", "2026-11-12"),
        ("INV-102", "10000.00", "2026-11-12"),
    ]
    assert case["review_tasks"] == []
    assert case["allowed_actions"]["approve"] is not None  # proposed commitments undecided
    listed = (await pod.get("/api/v1/pod/cases")).json()
    assert [c["stage"] for c in listed] == ["close"]  # sent, replied, nothing open
    for c in case["commitments"]:
        case = (
            await act(pod, case, "decide_commitment", commitment_id=c["id"], decision="approved")
        ).json()
    case = (await act(pod, case, "approve")).json()
    assert case["status"] == "approved"


async def test_reply_b_timesheets(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    text = "Please send approved timesheets for INV-101."
    case = await _reply(
        pod,
        ar_case,
        sent,
        text,
        fake_llm,
        read(
            document_requests=[{"kind": "timesheet", "invoice_numbers": ["INV-101"], "quote": text}]
        ),
    )
    (task,) = case["review_tasks"]
    assert task["kind"] == "missing_document"
    assert task["requirement"] == {"type": "document", "kind": "timesheet", "invoice": "INV-101"}
    r = await act(pod, case, "resolve_review_task", task_id=task["id"], resolution="sent them")
    assert r.status_code == 409  # only a matching approved document settles it

    url = f"/api/v1/pod/cases/{case['id']}/artifacts"
    copy = await pod.post(
        url,
        files={"file": ("inv.pdf", b"%PDF copy", "application/pdf")},
        data={"kind": "invoice_copy", "invoice_refs": "INV-101"},
    )
    await pod.post(
        f"/api/v1/pod/artifacts/{copy.json()['id']}/decision", json={"decision": "approved"}
    )
    case = await _case(pod, case["id"])
    assert case["review_tasks"][0]["status"] == "open"  # an invoice copy isn't a timesheet

    sheet = await pod.post(
        url,
        files={"file": ("ts.pdf", b"%PDF hours", "application/pdf")},
        data={"kind": "timesheet", "invoice_refs": "INV-101"},
    )
    await pod.post(
        f"/api/v1/pod/artifacts/{sheet.json()['id']}/decision", json={"decision": "approved"}
    )
    case = await _case(pod, case["id"])
    assert case["review_tasks"][0]["status"] == "resolved"
    assert "ts.pdf" in case["review_tasks"][0]["resolution"]


async def test_reply_c_date_only_from_the_customer(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    text = "Pay $6k now and $9k Nov 20 for INV-101."
    case = await _reply(
        pod,
        ar_case,
        sent,
        text,
        fake_llm,
        read(
            tranches=[
                tranche("INV-101", "6000", None, "Pay $6k now"),
                # The model guessed today's date for "now": not in the customer's words, dropped
                tranche("INV-101", "9000", "2026-11-20", "$9k Nov 20 for INV-101"),
            ]
        ),
    )
    by_amount = {c["amount"]: c for c in case["commitments"]}
    assert by_amount["6000.00"]["expected_date"] is None
    assert by_amount["9000.00"]["expected_date"] == "2026-11-20"
    (task,) = case["review_tasks"]
    assert task["kind"] == "unknown_date"
    r = await act(pod, case, "resolve_review_task", task_id=task["id"], resolution="Probably Nov 8")
    assert r.status_code == 409  # finance can't invent the date

    text2 = "The $6,000 will be paid on Nov 8."
    case = await _reply(
        pod,
        ar_case,
        sent,
        text2,
        fake_llm,
        read(
            tranches=[
                tranche("INV-101", "6000", "2026-11-08", text2),
            ]
        ),
    )
    by_amount = {c["amount"]: c for c in case["commitments"]}
    assert len(case["commitments"]) == 2  # the same promise, now dated
    assert by_amount["6000.00"]["expected_date"] == "2026-11-08"
    assert case["review_tasks"][0]["status"] == "resolved"


async def test_reply_d_partial_and_dispute(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    text = "$4k approved and $6k disputed on INV-102"
    case = await _reply(
        pod,
        ar_case,
        sent,
        text,
        fake_llm,
        read(
            tranches=[tranche("INV-102", "4000", None, "$4k approved")],
            disputes=[
                {
                    "invoice_number": "INV-102",
                    "amount": "6000",
                    "reason": "hours",
                    "quote": "$6k disputed on INV-102",
                }
            ],
        ),
    )
    assert [c["amount"] for c in case["commitments"]] == ["4000.00"]
    assert sorted(t["kind"] for t in case["review_tasks"]) == ["dispute", "unknown_date"]
    assert case["allowed_actions"]["approve"] is not None


async def test_unsupported_reading_is_never_used(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    case = await _reply(
        pod,
        ar_case,
        sent,
        "We will pay soon.",
        fake_llm,
        read(
            tranches=[
                tranche(
                    "INV-101", "15000", "2026-11-30", "We will pay all $15,000 on Nov 30"
                ),  # invented
            ]
        ),
    )
    assert case["commitments"] == []
    assert case["messages"][-1]["extraction_status"] == "failed"
    (task,) = case["review_tasks"]
    assert "wasn't read automatically" in task["detail"]

    fake_llm.error = LLMNotConfiguredError("none")
    r = await pod.post(
        f"/api/v1/pod/cases/{ar_case['id']}/replies",
        json={
            "from_email": CUSTOMER_EMAIL,
            "body": "Next week.",
            "reply_to_message_id": sent["id"],
        },
    )
    assert r.json()["extraction_status"] == "skipped"


async def test_low_confidence_and_conditions_go_to_a_person(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    text = "If the timesheets are approved we pay $15,000 on Nov 12. Maybe $10,000 on Nov 30."
    case = await _reply(
        pod,
        ar_case,
        sent,
        text,
        fake_llm,
        read(
            tranches=[
                tranche(
                    "INV-101",
                    "15000",
                    "2026-11-12",
                    "If the timesheets are approved we pay $15,000 on Nov 12",
                ),
                tranche(
                    "INV-102", "10000", "2026-11-30", "Maybe $10,000 on Nov 30", confidence=0.5
                ),
            ]
        ),
    )
    assert case["commitments"] == []
    assert len(case["review_tasks"]) == 2


async def test_reply_without_an_amount_is_a_review_task(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    # "Done" names no amount: the reading is still used, and a person asks the customer
    sent = await _send_request(pod, ar_case, fake_llm)
    case = await _reply(
        pod, ar_case, sent, "Done", fake_llm, read(tranches=[tranche("INV-101", "", None, "Done")])
    )
    assert case["messages"][-1]["extraction_status"] == "done"
    assert case["commitments"] == []
    (task,) = case["review_tasks"]
    assert task["kind"] == "ambiguity" and task["subject"] == "INV-101"
    assert "didn't say how much" in task["detail"]


async def test_unreadable_amount_is_explained_plainly(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    sent = await _send_request(pod, ar_case, fake_llm)
    case = await _reply(
        pod,
        ar_case,
        sent,
        "We pay a lot",
        fake_llm,
        read(tranches=[tranche("INV-101", "a lot", None, "We pay a lot")]),
    )
    message = case["messages"][-1]
    assert message["extraction_status"] == "failed"
    assert "couldn't read ('a lot')" in message["extraction"]["error"]


async def test_newer_source_must_be_taken_in(
    pod: AsyncClient, ar_case: dict[str, Any], entity: LegalEntity
) -> None:
    fresh = snapshot_payload(source_reference="later export")
    fresh["invoices"][1]["balance"] = "4000.00"
    newer = (await import_snapshot(pod, entity, fresh)).json()["snapshot"]
    case = await _case(pod, ar_case["id"])
    assert any("newer source" in b for b in case["blockers"])

    case = (await act(pod, case, "refresh_source", snapshot_id=newer["id"])).json()
    assert case["snapshot"]["id"] == newer["id"]
    assert case["state"]["total_open"] == "19000"
    assert not any("newer source" in b for b in case["blockers"])


async def test_portfolio(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    r = await pod.get("/api/v1/pod/ar/portfolio")
    assert r.status_code == 200, r.text
    p = r.json()
    assert Decimal(p["ar_balance"]) == 25000
    assert Decimal(p["overdue_over_30"]) == 25000  # 35 and 31 days overdue on Nov 5
    assert [c["name"] for c in p["customers"]] == ["Harbor Distribution"]
    harbor = p["customers"][0]
    assert harbor["open_case"]["reference"] == ar_case["reference"]
    assert harbor["next_action"] == "Draft the payment schedule request"
    assert {b["label"]: b["count"] for b in p["aging"]}["31-60"] == 2


@pytest.fixture(autouse=True)
def _no_real_llm(fake_llm: FakeLLM) -> FakeLLM:
    return fake_llm


async def test_ai_line_breaks_written_as_text_become_line_breaks(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    fake_llm.output = {
        "opening": "Dear AP,\\n\\nPlease confirm the dates.",
        "closing": "Thank you.\\n\\nBest regards,\\nFinance",
    }
    draft = (
        await pod.post(
            f"/api/v1/pod/cases/{ar_case['id']}/messages/compose",
            json={"purpose": "payment_schedule_request"},
        )
    ).json()
    assert draft["ai_drafted"] is True
    assert draft["body"].startswith("Dear AP,\n\nPlease confirm the dates.")
    assert "\\n" not in draft["body"]
