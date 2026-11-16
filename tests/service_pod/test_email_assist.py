"""AR cases: what each invoice is for, AI help writing the email, and the customer's own
saved email template."""

from typing import Any

from httpx import AsyncClient

from src.app.core.llm.base import LLMError
from src.app.entities.models import LegalEntity
from tests.conftest import FakeLLM
from tests.service_pod.conftest import import_snapshot, open_ar_case, snapshot_payload

POD = "/api/v1/pod"
SCHEDULE = "payment_schedule_request"


async def _compose(pod: AsyncClient, case: dict[str, Any]) -> dict[str, Any]:
    r = await pod.post(f"{POD}/cases/{case['id']}/messages/compose", json={"purpose": SCHEDULE})
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    return result


async def _assist(pod: AsyncClient, case: dict[str, Any], **body: Any) -> Any:
    return await pod.post(
        f"{POD}/cases/{case['id']}/messages/assist",
        json={"purpose": SCHEDULE, "instruction": "make it firmer", **body},
    )


async def test_each_invoice_shows_what_it_is_for(pod: AsyncClient, entity: LegalEntity) -> None:
    payload = snapshot_payload()
    payload["invoices"][0]["details"] = {
        "lines": [
            {
                "item": "Consulting",
                "description": "Priya Shah - Java Developer, October",
                "service_date": "2026-09-30",
                "quantity": "160",
                "rate": "75",
                "amount": "12000.00",
            }
        ],
        "custom_fields": {"Consultant": "Priya Shah", "PO": "PO-77"},
    }
    r = await import_snapshot(pod, entity, payload)
    assert r.status_code == 201, r.text
    case = await open_ar_case(pod, r.json()["snapshot"])
    detail = (await pod.get(f"{POD}/cases/{case['id']}")).json()
    first = detail["state"]["invoices"][0]
    assert first["details"]["custom_fields"]["Consultant"] == "Priya Shah"
    assert first["details"]["lines"][0]["description"] == "Priya Shah - Java Developer, October"
    assert detail["state"]["invoices"][1]["details"] is None


async def test_ai_rewrites_the_email_and_keeps_the_table(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    draft = await _compose(pod, ar_case)
    fake_llm.output = {
        "subject": "Overdue invoices INV-101 / INV-102",
        "body": "Dear Harbor team,\n\nThese are overdue.\n\n[INVOICE TABLE]\n\nRegards",
    }
    r = await _assist(pod, ar_case, subject=draft["subject"], body=draft["body"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert draft["fact_block"] in out["body"] and "[INVOICE TABLE]" not in out["body"]
    assert "The table below" not in fake_llm.calls[-1][1]
    assert "[INVOICE TABLE]" in fake_llm.calls[-1][1]  # the AI never saw the figures as text

    # It is a valid draft: the verified figures are there exactly
    saved = await pod.post(
        f"{POD}/cases/{ar_case['id']}/messages",
        json={
            "audience": "customer",
            "purpose": SCHEDULE,
            "to_email": draft["to_email"],
            "subject": out["subject"],
            "body": out["body"],
        },
    )
    assert saved.status_code == 201, saved.text


async def test_ai_writes_from_plain_english(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    fake_llm.output = {"subject": "Payment reminder", "body": "Hello,\n\n[INVOICE TABLE]\n\nThanks"}
    r = await _assist(pod, ar_case, instruction="write a friendly first reminder")
    assert r.status_code == 200, r.text
    assert "INV-101" in r.json()["body"]
    assert "(empty: write a new email)" in fake_llm.calls[-1][1]


async def test_ai_may_not_add_figures_or_drop_the_table(
    pod: AsyncClient, ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    fake_llm.output = {"subject": "Reminder", "body": "Please pay 4999 today.\n[INVOICE TABLE]"}
    r = await _assist(pod, ar_case)
    assert r.status_code == 409
    assert "4999" in r.json()["detail"]["message"]

    fake_llm.output = {"subject": "Reminder", "body": "Please pay soon."}
    r = await _assist(pod, ar_case)
    assert r.status_code == 409
    assert "placeholder" in r.json()["detail"]["message"]

    fake_llm.error = LLMError("offline")
    r = await _assist(pod, ar_case)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "ai_unavailable"


async def test_the_customer_template_is_used_for_every_new_draft(
    pod: AsyncClient, ar_case: dict[str, Any]
) -> None:
    url = f"{POD}/cases/{ar_case['id']}/template"
    assert (await pod.get(url)).json() is None
    draft = await _compose(pod, ar_case)
    body = (
        f"Hi Harbor AP,\n\nOur usual monthly note.\n\n{draft['fact_block']}\n\nBest,\nE-Solutions"
    )
    r = await pod.put(
        url,
        json={"purpose": SCHEDULE, "subject": "Harbor: INV-101 / INV-102", "body": body},
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["subject"] == "Harbor: {{invoice_numbers}}"
    assert "{{invoices}}" in saved["body"] and "15,000.00" not in saved["body"]

    again = await _compose(pod, ar_case)
    assert again["subject"] == "Harbor: INV-101 / INV-102"
    assert again["body"].startswith("Hi Harbor AP,") and draft["fact_block"] in again["body"]
    assert "saved email template" in (again["note"] or "")

    assert (await pod.delete(url)).status_code == 204
    assert "saved email template" not in ((await _compose(pod, ar_case))["note"] or "")


async def test_a_template_keeps_the_invoice_table(
    pod: AsyncClient, ar_case: dict[str, Any]
) -> None:
    r = await pod.put(
        f"{POD}/cases/{ar_case['id']}/template",
        json={"purpose": SCHEDULE, "subject": "Hi", "body": "Please pay."},
    )
    assert r.status_code == 409
