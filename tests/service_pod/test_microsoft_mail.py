"""Sending from a Microsoft 365 mailbox and reading customer replies back from it. Microsoft
Graph is a stand-in here (httpx MockTransport): no mail ever leaves a test."""

import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import get_settings
from src.app.core.llm.base import LLMNotConfiguredError
from src.app.entities.models import LegalEntity
from src.app.jobs.queue import JobContext
from src.app.service_pod.core.messaging import graph
from src.app.service_pod.core.messaging.graph import GraphMailbox
from src.app.service_pod.core.messaging.mailbox_job import read_mailbox
from src.app.service_pod.core.messaging.models import PodMailboxCursor
from tests.conftest import FakeLLM
from tests.service_pod.conftest import (
    CUSTOMER_EMAIL,
    import_snapshot,
    open_ar_case,
    snapshot_payload,
)

MAILBOX = "finance@esolutions.example"
SENT_ID = "<sent-1@esolutions.prod.outlook.com>"
CHECKS = {"recipient": True, "mapping": True, "tone": True}


class FakeGraph:
    """Answers like Microsoft: a token, drafts, send, and an inbox with replies."""

    def __init__(self) -> None:
        self.drafts: list[dict[str, Any]] = []
        self.sent: list[str] = []
        self.inbox: list[dict[str, Any]] = []
        self.mime: dict[str, str] = {}
        self.fetched: list[str] = []
        self.send_status = 202
        self.draft_status = 201

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "t0ken", "expires_in": 3599})
        assert request.headers["authorization"] == "Bearer t0ken"
        base = f"/v1.0/users/{MAILBOX}"
        if request.method == "POST" and path == f"{base}/messages":
            if self.draft_status != 201:
                return httpx.Response(self.draft_status, json={"error": {"message": "bad"}})
            self.drafts.append(json.loads(request.content))
            return httpx.Response(201, json={"id": "D1", "internetMessageId": SENT_ID})
        if request.method == "POST" and path == f"{base}/messages/D1/send":
            if self.send_status != 202:
                return httpx.Response(self.send_status, json={"error": {"message": "busy"}})
            self.sent.append("D1")
            return httpx.Response(202)
        if path == f"{base}/mailFolders/inbox/messages":
            return httpx.Response(200, json={"value": self.inbox})
        if path.startswith(f"{base}/messages/") and path.endswith("/$value"):
            mail_id = path.split("/")[-2]
            self.fetched.append(mail_id)
            return httpx.Response(200, content=self.mime[mail_id].encode())
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
    fake = FakeGraph()
    settings = get_settings()
    monkeypatch.setattr(settings, "email_provider", "microsoft")
    monkeypatch.setattr(settings, "email_sender", None)
    monkeypatch.setattr(settings, "mailbox_poll_seconds", 60)
    monkeypatch.setattr(graph, "_tokens", {})
    mailbox = GraphMailbox("tenant", "client", "secret", MAILBOX, 5, httpx.MockTransport(fake))
    monkeypatch.setattr(GraphMailbox, "from_settings", classmethod(lambda cls: mailbox))
    return fake


async def _send(pod: AsyncClient, case: dict[str, Any]) -> dict[str, Any]:
    draft = (
        await pod.post(
            f"/api/v1/pod/cases/{case['id']}/messages",
            json={
                "audience": "customer",
                "purpose": "case_message",
                "to_email": CUSTOMER_EMAIL,
                "subject": "Confirm payment schedule",
                "body": "Please confirm when INV-101 and INV-102 will be paid.",
            },
        )
    ).json()
    r = await pod.post(
        f"/api/v1/pod/messages/{draft['id']}/send",
        json={"expected_version": draft["version"], "checks": CHECKS},
    )
    return r.json()  # type: ignore[no-any-return]


async def test_sends_from_the_mailbox(
    pod: AsyncClient, ar_case: dict[str, Any], fake_graph: FakeGraph
) -> None:
    status = (await pod.get("/api/v1/pod/email-status")).json()
    assert (status["provider"], status["ready"], status["sender"]) == ("microsoft", True, MAILBOX)

    msg = await _send(pod, ar_case)
    assert msg["status"] == "sent", msg
    assert msg["simulated"] is False
    assert msg["provider_message_id"] == SENT_ID  # what the customer's reply will quote
    (draft,) = fake_graph.drafts
    assert draft["toRecipients"] == [{"emailAddress": {"address": CUSTOMER_EMAIL}}]
    assert draft["subject"] == "Confirm payment schedule"
    assert "from" not in draft  # sent as the mailbox itself
    assert fake_graph.sent == ["D1"]


async def test_unclear_and_refused_sends(
    pod: AsyncClient, ar_case: dict[str, Any], fake_graph: FakeGraph
) -> None:
    fake_graph.draft_status = 400  # only a draft was refused: nothing went out
    assert (await _send(pod, ar_case))["status"] == "send_failed"

    fake_graph.draft_status = 201
    fake_graph.send_status = 503  # it may have gone: a person checks Sent Items
    msg = await _send(pod, ar_case)
    assert msg["status"] == "send_unknown"
    assert "Sent Items" in msg["error"]


async def test_demo_data_only_goes_to_the_tester(
    pod: AsyncClient,
    entity: LegalEntity,
    fake_graph: FakeGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = snapshot_payload(provenance="SYNTHETIC_DEMO", source_reference="sandbox")
    snap = (await import_snapshot(pod, entity, demo)).json()["snapshot"]
    case = await open_ar_case(pod, snap)

    msg = await _send(pod, case)
    assert "EMAIL_TEST_RECIPIENT" in msg["detail"]["message"]
    assert fake_graph.drafts == []

    monkeypatch.setattr(get_settings(), "email_test_recipient", "me@esolutions.example")
    case = (await pod.get(f"/api/v1/pod/cases/{case['id']}")).json()
    draft = next(m for m in case["messages"] if m["status"] == "draft")
    r = await pod.post(
        f"/api/v1/pod/messages/{draft['id']}/send",
        json={"expected_version": draft["version"], "checks": CHECKS},
    )
    assert r.json()["status"] == "sent"
    (sent,) = fake_graph.drafts
    assert sent["toRecipients"] == [{"emailAddress": {"address": "me@esolutions.example"}}]
    assert sent["subject"] == f"[TEST for {CUSTOMER_EMAIL}] Confirm payment schedule"


def _reply(sender: str, in_reply_to: str, message_id: str) -> str:
    return (
        f"From: Harbor AP <{sender}>\r\n"
        f"To: {MAILBOX}\r\n"
        "Subject: RE: Confirm payment schedule\r\n"
        f"Message-ID: {message_id}\r\n"
        f"In-Reply-To: {in_reply_to}\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><p>Pay both on Nov 12.</p><p>Thanks,<br>Harbor</p></body></html>\r\n"
    )


async def test_replies_are_read_from_the_inbox(
    pod: AsyncClient,
    ar_case: dict[str, Any],
    fake_graph: FakeGraph,
    fake_llm: FakeLLM,
    db: AsyncSession,
) -> None:
    await _send(pod, ar_case)
    fake_graph.inbox = [
        {  # someone the case never wrote to: not even opened
            "id": "N1",
            "from": {"emailAddress": {"address": "news@vendor.example"}},
            "receivedDateTime": "2099-01-01T08:00:00Z",
        },
        {
            "id": "R1",
            "from": {"emailAddress": {"address": CUSTOMER_EMAIL.upper()}},
            "receivedDateTime": "2099-01-01T09:00:00Z",
        },
    ]
    fake_graph.mime["R1"] = _reply(CUSTOMER_EMAIL, SENT_ID, "<reply-1@harbor.example>")
    fake_llm.error = LLMNotConfiguredError("none")  # reading the reply isn't this test

    ctx = JobContext(fake_llm, 1, 1)  # type: ignore[arg-type]
    await read_mailbox(db, {}, ctx)
    await read_mailbox(db, {}, ctx)  # the same mail again: imported once

    assert fake_graph.fetched == ["R1", "R1"]
    case = (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).json()
    (reply,) = [m for m in case["messages"] if m["direction"] == "inbound"]
    assert reply["thread_evidence"] == "header"
    assert reply["created_by"] is None  # read by the worker
    assert reply["body"].startswith("Pay both on Nov 12.")
    cursor = await db.scalar(select(PodMailboxCursor))
    assert cursor is not None and cursor.received_after.year == 2099


async def test_sandbox_may_mail_the_quickbooks_contact_only(
    pod: AsyncClient,
    entity: LegalEntity,
    fake_graph: FakeGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "email_sandbox_to_quickbooks_contacts", True)
    demo = snapshot_payload(provenance="SYNTHETIC_DEMO", source_reference="sandbox")
    snap = (await import_snapshot(pod, entity, demo)).json()["snapshot"]
    case = await open_ar_case(pod, snap)

    msg = await _send(pod, case)
    assert msg["status"] == "sent", msg
    (sent,) = fake_graph.drafts
    assert sent["toRecipients"] == [{"emailAddress": {"address": CUSTOMER_EMAIL}}]
    assert sent["subject"] == "Confirm payment schedule"  # the real recipient: no test label

    # On sandbox data a draft may name any address; it still can't go out
    draft = (
        await pod.post(
            f"/api/v1/pod/cases/{case['id']}/messages",
            json={
                "audience": "customer",
                "purpose": "case_message",
                "to_email": "someone@else.example",
                "subject": "s",
                "body": "b",
            },
        )
    ).json()
    r = await pod.post(
        f"/api/v1/pod/messages/{draft['id']}/send",
        json={"expected_version": draft["version"], "checks": CHECKS},
    )
    assert r.status_code == 409
    assert "as QuickBooks states it" in r.json()["detail"]["message"]
    assert len(fake_graph.drafts) == 1
