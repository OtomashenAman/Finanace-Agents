from typing import Any

import pytest
from httpx import AsyncClient

from src.app.core.config import get_settings
from src.app.service_pod.messaging import providers
from tests.service_pod.conftest import CUSTOMER_EMAIL

DRAFT = {
    "audience": "customer",
    "purpose": "payment_schedule_request",
    "to_email": CUSTOMER_EMAIL,
    "subject": "Confirm payment schedule for INV-101 / INV-102",
    "body": "Our records show INV-101 ($15,000) and INV-102 ($10,000) outstanding.",
}


async def _draft(client: AsyncClient, case: dict[str, Any], **changes: Any) -> Any:
    return await client.post(f"/api/v1/pod/cases/{case['id']}/messages", json={**DRAFT, **changes})


async def _post(client: AsyncClient, url: str, message: dict[str, Any], **body: Any) -> Any:
    return await client.post(url, json={"expected_version": message["version"], **body})


async def _sent(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> dict[str, Any]:
    msg = (await _draft(ar_team["prep"], ar_case)).json()
    msg = (await _post(ar_team["rev"], f"/api/v1/pod/messages/{msg['id']}/approve", msg)).json()
    r = await _post(ar_team["prep"], f"/api/v1/pod/messages/{msg['id']}/send", msg)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_customer_mail_only_to_the_verified_contact(
    ar_team: dict[str, Any], ar_case: dict[str, Any]
) -> None:
    r = await _draft(ar_team["prep"], ar_case, to_email="someone@else.example")
    assert r.status_code == 409
    assert "verified contact" in r.json()["detail"]["message"]
    # Cobalt's contact is real, but this case is about Harbor
    r = await _draft(ar_team["prep"], ar_case, to_email="pay@cobalt.example")
    assert r.status_code == 409

    r = await _draft(ar_team["prep"], ar_case, audience="internal", to_email="cfo@example.com")
    assert r.status_code == 409  # not a configured internal recipient


async def test_approve_edit_send_once(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> None:
    prep, rev = ar_team["prep"], ar_team["rev"]
    msg = (await _draft(prep, ar_case)).json()
    assert msg["status"] == "draft"

    r = await _post(prep, f"/api/v1/pod/messages/{msg['id']}/approve", msg)
    assert r.status_code == 409  # the author can't approve

    approved = (await _post(rev, f"/api/v1/pod/messages/{msg['id']}/approve", msg)).json()
    assert approved["status"] == "approved"
    assert approved["provider"] == "outbox"

    # Editing withdraws the approval
    r = await prep.patch(
        f"/api/v1/pod/messages/{msg['id']}",
        json={"expected_version": approved["version"], "body": DRAFT["body"] + " Thanks."},
    )
    edited = r.json()
    assert edited["status"] == "draft"
    assert edited["approved_by"] is None
    r = await _post(prep, f"/api/v1/pod/messages/{msg['id']}/send", edited)
    assert r.status_code == 409

    approved = (await _post(rev, f"/api/v1/pod/messages/{msg['id']}/approve", edited)).json()
    sent = (await _post(prep, f"/api/v1/pod/messages/{msg['id']}/send", approved)).json()
    assert sent["status"] == "sent"
    assert sent["simulated"] is True  # outbox: nothing left the application
    assert sent["provider_message_id"].startswith("<outbox-")

    r = await _post(prep, f"/api/v1/pod/messages/{msg['id']}/send", sent)
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
    ar_team: dict[str, Any], ar_case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(providers, "get_email_provider", lambda: _Unclear())
    msg = await _sent(ar_team, ar_case)
    assert msg["status"] == "send_unknown"

    case = (await ar_team["prep"].get(f"/api/v1/pod/cases/{ar_case['id']}")).json()
    assert any("reconciled" in b for b in case["completion_blockers"])

    url = f"/api/v1/pod/messages/{msg['id']}/reconcile"
    r = await _post(ar_team["prep"], url, msg, outcome="sent", note="checked Brevo log")
    assert r.status_code == 409  # a reviewer reconciles
    r = await _post(ar_team["rev"], url, msg, outcome="sent", note="Brevo log shows delivered")
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


async def test_reply_import(ar_team: dict[str, Any], ar_case: dict[str, Any]) -> None:
    sent = await _sent(ar_team, ar_case)
    url = f"/api/v1/pod/cases/{ar_case['id']}/replies"

    r = await ar_team["prep"].post(url, json={"raw_eml": _eml(sent, sender="x@evil.example")})
    assert r.status_code == 422  # not the address the message went to

    r = await ar_team["prep"].post(url, json={"raw_eml": _eml(sent)})
    assert r.status_code == 201, r.text
    reply = r.json()
    assert reply["direction"] == "inbound"
    assert reply["thread_evidence"] == "header"
    assert reply["in_reply_to_id"] == sent["id"]

    r = await ar_team["prep"].post(url, json={"raw_eml": _eml(sent)})
    assert r.status_code == 200  # the same email again: the existing reply
    r = await ar_team["prep"].post(url, json={"raw_eml": _eml(sent, body="Pay on Dec 1.")})
    assert r.status_code == 409  # same Message-ID, different content

    unthreaded = _eml(sent).replace(f"In-Reply-To: {sent['provider_message_id']}\r\n", "")
    r = await ar_team["prep"].post(url, json={"raw_eml": unthreaded})
    assert r.status_code == 422

    r = await ar_team["prep"].post(url, json={"from_email": CUSTOMER_EMAIL, "body": "ok"})
    assert r.status_code == 422  # pasted: must say which message it answers
    r = await ar_team["prep"].post(
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
    ar_team: dict[str, Any], ar_case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "pod_internal_recipients", ["cfo@example.com"])
    r = await _draft(ar_team["prep"], ar_case, audience="internal", to_email="CFO@example.com")
    assert r.status_code == 201


async def test_attachments_must_be_approved_documents(
    ar_team: dict[str, Any], ar_case: dict[str, Any]
) -> None:
    prep, rev = ar_team["prep"], ar_team["rev"]
    url = f"/api/v1/pod/cases/{ar_case['id']}/artifacts"
    files = {"file": ("timesheet.pdf", b"%PDF-1.4 hours", "application/pdf")}
    r = await prep.post(url, files=files, data={"kind": "timesheet", "invoice_refs": "INV-999"})
    assert r.status_code == 422  # not an invoice of this case
    r = await prep.post(url, files=files, data={"kind": "timesheet", "invoice_refs": "INV-101"})
    assert r.status_code == 201, r.text
    artifact = r.json()

    r = await _draft(prep, ar_case, artifact_ids=[artifact["id"]])
    assert r.status_code == 409  # not approved yet

    decision = f"/api/v1/pod/artifacts/{artifact['id']}/decision"
    assert (await prep.post(decision, json={"decision": "approved"})).status_code == 409
    assert (await rev.post(decision, json={"decision": "approved"})).json()["status"] == "approved"

    r = await _draft(prep, ar_case, artifact_ids=[artifact["id"]])
    assert r.status_code == 201
    content = await rev.get(f"/api/v1/pod/artifacts/{artifact['id']}/content")
    assert content.content == b"%PDF-1.4 hours"
