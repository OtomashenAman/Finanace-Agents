from typing import Any

import pytest
from httpx import AsyncClient

from src.app.core.config import get_settings
from src.app.service_pod.core.messaging import providers
from tests.conftest import FakeLLM
from tests.service_pod.conftest import CUSTOMER_EMAIL, act

DRAFT = {
    "audience": "customer",
    "purpose": "case_message",  # generic: no fact block (see test_ar_flow for those)
    "to_email": CUSTOMER_EMAIL,
    "subject": "Confirm payment schedule for INV-101 / INV-102",
    "body": "Our records show INV-101 ($15,000) and INV-102 ($10,000) outstanding.",
}


async def _draft(client: AsyncClient, case: dict[str, Any], **changes: Any) -> Any:
    return await client.post(f"/api/v1/pod/cases/{case['id']}/messages", json={**DRAFT, **changes})


CHECKS = {"recipient": True, "mapping": True, "tone": True}


async def _post(client: AsyncClient, url: str, message: dict[str, Any], **body: Any) -> Any:
    if url.endswith("/send"):
        body.setdefault("checks", CHECKS)
    return await client.post(url, json={"expected_version": message["version"], **body})


async def _sent(pod: AsyncClient, ar_case: dict[str, Any]) -> dict[str, Any]:
    msg = (await _draft(pod, ar_case)).json()
    r = await _post(pod, f"/api/v1/pod/messages/{msg['id']}/send", msg)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_customer_mail_only_to_the_verified_contact(
    pod: AsyncClient, ar_case: dict[str, Any]
) -> None:
    r = await _draft(pod, ar_case, to_email="someone@else.example")
    assert r.status_code == 409
    assert "verified contact" in r.json()["detail"]["message"]
    # Cobalt's contact is real, but this case is about Harbor
    r = await _draft(pod, ar_case, to_email="pay@cobalt.example")
    assert r.status_code == 409

    r = await _draft(pod, ar_case, audience="internal", to_email="cfo@example.com")
    assert r.status_code == 409  # not a configured internal recipient


async def test_edit_then_send_once(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    msg = (await _draft(pod, ar_case)).json()
    assert msg["status"] == "draft"
    url = f"/api/v1/pod/messages/{msg['id']}/send"

    r = await _post(pod, url, msg, checks={})
    assert r.status_code == 409  # recipient, mapping and tone must be confirmed

    r = await pod.patch(
        f"/api/v1/pod/messages/{msg['id']}",
        json={"expected_version": msg["version"], "body": DRAFT["body"] + " Thanks."},
    )
    edited = r.json()
    assert edited["status"] == "draft"

    sent = (await _post(pod, url, edited)).json()
    assert sent["status"] == "sent"
    assert sent["provider"] == "outbox"
    assert sent["simulated"] is True  # outbox: nothing left the application
    assert sent["provider_message_id"].startswith("<outbox-")

    r = await _post(pod, url, sent)
    assert r.status_code == 409  # never sent twice


class _Unclear:
    name = "outbox"
    simulated = True
    sender = "finance-outbox@localhost"

    async def readiness(self) -> str | None:
        return None

    async def send(self, email: providers.OutgoingEmail) -> str:
        raise providers.SendUncertainError("timeout")


async def test_unclear_send_needs_reconciling(
    pod: AsyncClient, ar_case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(providers, "get_email_provider", lambda: _Unclear())
    msg = await _sent(pod, ar_case)
    assert msg["status"] == "send_unknown"

    case = (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).json()
    assert any("reconciled" in b for b in case["completion_blockers"])

    url = f"/api/v1/pod/messages/{msg['id']}/reconcile"
    r = await _post(pod, url, msg, outcome="sent", note="Brevo log shows delivered")
    assert r.json()["status"] == "sent"


def _eml(
    sent: dict[str, Any], sender: str = CUSTOMER_EMAIL, body: str = "Pay both on Nov 12."
) -> str:
    return (
        f"From: Harbor AP <{sender}>\r\n"
        "To: finance-outbox@localhost\r\n"
        "Subject: Re: Confirm payment schedule\r\n"
        "Message-ID: <reply-1@harbor.example>\r\n"
        f"In-Reply-To: {sent['provider_message_id']}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{body}\r\n"
    )


async def test_reply_import(pod: AsyncClient, ar_case: dict[str, Any]) -> None:
    sent = await _sent(pod, ar_case)
    url = f"/api/v1/pod/cases/{ar_case['id']}/replies"

    r = await pod.post(url, json={"raw_eml": _eml(sent, sender="x@evil.example")})
    assert r.status_code == 422  # not the address the message went to

    r = await pod.post(url, json={"raw_eml": _eml(sent)})
    assert r.status_code == 201, r.text
    reply = r.json()
    assert reply["direction"] == "inbound"
    assert reply["thread_evidence"] == "header"
    assert reply["in_reply_to_id"] == sent["id"]

    r = await pod.post(url, json={"raw_eml": _eml(sent)})
    assert r.status_code == 200  # the same email again: the existing reply
    r = await pod.post(url, json={"raw_eml": _eml(sent, body="Pay on Dec 1.")})
    assert r.status_code == 409  # same Message-ID, different content

    unthreaded = _eml(sent).replace(f"In-Reply-To: {sent['provider_message_id']}\r\n", "")
    r = await pod.post(url, json={"raw_eml": unthreaded})
    assert r.status_code == 422

    r = await pod.post(url, json={"from_email": CUSTOMER_EMAIL, "body": "ok"})
    assert r.status_code == 422  # pasted: must say which message it answers
    r = await pod.post(
        url,
        json={
            "from_email": CUSTOMER_EMAIL,
            "body": "Send timesheets",
            "reply_to_message_id": sent["id"],
        },
    )
    assert r.status_code == 201
    assert r.json()["thread_evidence"] == "manual"


async def test_internal_recipients_are_configured(
    pod: AsyncClient, ar_case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "pod_internal_recipients", ["cfo@example.com"])
    r = await _draft(pod, ar_case, audience="internal", to_email="CFO@example.com")
    assert r.status_code == 201


async def test_attachments_must_be_approved_documents(
    pod: AsyncClient, ar_case: dict[str, Any]
) -> None:
    url = f"/api/v1/pod/cases/{ar_case['id']}/artifacts"
    files = {"file": ("timesheet.pdf", b"%PDF-1.4 hours", "application/pdf")}
    r = await pod.post(url, files=files, data={"kind": "timesheet", "invoice_refs": "INV-999"})
    assert r.status_code == 422  # not an invoice of this case
    r = await pod.post(url, files=files, data={"kind": "timesheet", "invoice_refs": "INV-101"})
    assert r.status_code == 201, r.text
    artifact = r.json()

    r = await _draft(pod, ar_case, artifact_ids=[artifact["id"]])
    assert r.status_code == 409  # not approved yet

    decision = f"/api/v1/pod/artifacts/{artifact['id']}/decision"
    assert (await pod.post(decision, json={"decision": "approved"})).json()["status"] == "approved"

    r = await _draft(pod, ar_case, artifact_ids=[artifact["id"]])
    assert r.status_code == 201
    content = await pod.get(f"/api/v1/pod/artifacts/{artifact['id']}/content")
    assert content.content == b"%PDF-1.4 hours"


async def test_a_reply_after_closing_is_kept_not_read(
    pod: AsyncClient, answered_ar_case: dict[str, Any], fake_llm: FakeLLM
) -> None:
    case = (await act(pod, answered_ar_case, "approve")).json()
    case = (await act(pod, case, "complete")).json()
    sent = next(m for m in case["messages"] if m["direction"] == "outbound")
    calls = len(fake_llm.calls)

    r = await pod.post(
        f"/api/v1/pod/cases/{case['id']}/replies",
        json={
            "from_email": CUSTOMER_EMAIL,
            "body": "We will pay on Dec 1.",
            "reply_to_message_id": sent["id"],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["extraction_status"] == "case_closed"
    assert len(fake_llm.calls) == calls  # not read into the case

    after = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    assert (after["status"], after["version"]) == ("completed", case["version"])
    assert after["commitments"] == []
    inbox = (await pod.get("/api/v1/pod/messages")).json()
    assert inbox[0]["extraction_status"] == "case_closed"
