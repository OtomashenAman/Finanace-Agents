"""Sending from a Microsoft 365 mailbox and reading customer replies back from it. Microsoft
Graph is a stand-in here (httpx MockTransport): no mail ever leaves a test."""

import json
import time
from datetime import UTC, datetime
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
from src.app.service_pod.core.messaging.inbound import answers_subject
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


# --- the app token: expiry across sleep, and a rejected token -----------------------------------


class TokenGraph:
    """Microsoft that issues tokens in turn and rejects `revoked` ones on Graph (401)."""

    def __init__(self, *tokens: str) -> None:
        self.tokens = list(tokens)
        self.issued: list[str] = []
        self.revoked: set[str] = set()
        self.graph_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/v2.0/token"):
            token = self.tokens[min(len(self.issued), len(self.tokens) - 1)]
            self.issued.append(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 3599})
        self.graph_calls += 1
        if request.headers["authorization"].removeprefix("Bearer ") in self.revoked:
            return httpx.Response(401, json={"error": {"message": "Invalid token lifetime."}})
        return httpx.Response(200, json={"value": []})


def token_mailbox(fake: TokenGraph) -> GraphMailbox:
    return GraphMailbox("tenant", "client", "secret", MAILBOX, 5, httpx.MockTransport(fake))


async def test_a_token_that_expired_while_the_machine_slept_is_renewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Cached an hour ago by the wall clock (the monotonic clock may not have moved in sleep)
    monkeypatch.setattr(graph, "_tokens", {("tenant", "client"): ("old", time.time() - 5)})
    fake = TokenGraph("new")
    await token_mailbox(fake).inbox_since(datetime(2026, 11, 1, tzinfo=UTC))
    assert fake.issued == ["new"]


async def test_a_rejected_token_is_replaced_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph, "_tokens", {})
    fake = TokenGraph("stale", "fresh")
    fake.revoked = {"stale"}
    assert await token_mailbox(fake).inbox_since(datetime(2026, 11, 1, tzinfo=UTC)) == []
    assert fake.issued == ["stale", "fresh"] and fake.graph_calls == 2


async def test_a_token_rejected_again_is_an_error_not_a_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph, "_tokens", {})
    fake = TokenGraph("bad")
    fake.revoked = {"bad"}
    with pytest.raises(graph.GraphError) as error:
        await token_mailbox(fake).inbox_since(datetime(2026, 11, 1, tzinfo=UTC))
    assert error.value.status == 401 and fake.graph_calls == 2


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


def _reply(
    sender: str,
    in_reply_to: str | None,
    message_id: str,
    subject: str = "RE: Confirm payment schedule",
) -> str:
    """A reply as the customer's mail app sends it; in_reply_to None: an app that sends no
    reply headers at all (e.g. yopmail)."""
    thread = f"In-Reply-To: {in_reply_to}\r\n" if in_reply_to else ""
    return (
        f"From: Harbor AP <{sender}>\r\n"
        f"To: {MAILBOX}\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {message_id}\r\n"
        f"{thread}"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><p>Pay both on Nov 12.</p><p>Thanks,<br>Harbor</p></body></html>\r\n"
    )


def _inbox_item(mail_id: str, sender: str, received: str) -> dict[str, Any]:
    return {"id": mail_id, "from": {"emailAddress": {"address": sender}},
            "receivedDateTime": received}  # fmt: skip


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
    # Graph returns the same mail again (its "after" filter is finer than the time it gives):
    # remembered as seen, it isn't even downloaded twice
    await read_mailbox(db, {}, ctx)

    assert fake_graph.fetched == ["R1"]
    case = (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).json()
    (reply,) = [m for m in case["messages"] if m["direction"] == "inbound"]
    assert reply["thread_evidence"] == "header"
    assert reply["created_by"] is None  # read by the worker
    assert reply["body"].startswith("Pay both on Nov 12.")
    cursor = await db.scalar(select(PodMailboxCursor))
    assert cursor is not None and cursor.received_after.year == 2099


async def test_a_reply_without_reply_headers_is_matched_by_its_subject(
    pod: AsyncClient,
    ar_case: dict[str, Any],
    fake_graph: FakeGraph,
    fake_llm: FakeLLM,
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _send(pod, ar_case)
    fake_graph.inbox = [
        _inbox_item("Y1", CUSTOMER_EMAIL, "2099-01-01T09:00:00Z"),  # "Re: " + our subject
        _inbox_item("Y2", CUSTOMER_EMAIL, "2099-01-01T09:05:00Z"),  # another subject
    ]
    fake_graph.mime["Y1"] = _reply(CUSTOMER_EMAIL, None, "<y1@yopmail.com>")
    fake_graph.mime["Y2"] = _reply(CUSTOMER_EMAIL, None, "<y2@yopmail.com>", "Holiday hours")
    fake_llm.error = LLMNotConfiguredError("none")

    with caplog.at_level("INFO", logger="src.app.service_pod.core.messaging.mailbox_job"):
        await read_mailbox(db, {}, JobContext(fake_llm, 1, 1))  # type: ignore[arg-type]

    case = (await pod.get(f"/api/v1/pod/cases/{ar_case['id']}")).json()
    (reply,) = [m for m in case["messages"] if m["direction"] == "inbound"]
    assert reply["thread_evidence"] == "subject"  # weaker than headers: shown to the reviewer
    assert reply["body"].startswith("Pay both on Nov 12.")
    assert "imported Y1" in caplog.text and "(subject match)" in caplog.text
    assert "skipped Y2" in caplog.text and "no reply headers" in caplog.text


@pytest.mark.parametrize(
    ("reply", "sent", "answers"),
    [
        ("Re: Confirm payment schedule", "Confirm payment schedule", True),
        ("RE: RE:  confirm payment  SCHEDULE", "Confirm payment schedule", True),
        ("AW: Confirm payment schedule", "Confirm payment schedule", True),
        ("Confirm payment schedule", "Confirm payment schedule", False),  # no reply prefix
        ("Re: Confirm payment schedule for 1039", "Confirm payment schedule for 1038", False),
        ("Fwd: Confirm payment schedule", "Confirm payment schedule", False),  # a forward
    ],
)
def test_what_counts_as_answering_a_subject(reply: str, sent: str, answers: bool) -> None:
    assert answers_subject(reply, sent) is answers


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
