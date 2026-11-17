"""E-signature through PandaDoc. PandaDoc is a stand-in (httpx MockTransport): nothing leaves
a test. Each person sees only the templates they uploaded and the documents they sent."""

import hashlib
import hmac
import io
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from docx import Document
from httpx import AsyncClient
from pydantic import SecretStr

from src.app.auth.models import UserRole
from src.app.core.config import get_settings
from src.app.esign import pandadoc, service
from src.app.finance_pod.pdf import render as render_pdf
from tests.conftest import ClientFactory, MakeUser

PDF = b"%PDF-1.7\n{signature:signer1___}\n%%EOF"
WEBHOOK_KEY = "shared-key"


class FakePandaDoc:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.uploads: list[dict[str, Any]] = []
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.polls_until_draft = 1  # status reads that still say document.uploaded
        self.refuse_upload: str | None = None
        self.fields: list[tuple[str, list[dict[str, Any]]]] = []
        self.sessions: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "API-Key test-key"
        path = request.url.path
        if request.method == "POST" and path == "/public/v1/documents":
            if self.refuse_upload:
                return httpx.Response(400, json={"detail": self.refuse_upload})
            body = request.content
            assert b'name="file"' in body and b"%PDF" in body
            start = body.index(b'name="data"')
            data = json.loads(body[body.index(b"{", start) : body.index(b"\r\n--", start)])
            doc_id = f"pd{len(self.documents) + 1}"
            self.documents[doc_id] = {"status": "document.uploaded", "polls": 0}
            self.uploads.append(data)
            self.documents[doc_id]["recipients"] = [
                {"id": f"r-{r['role']}", "email": r["email"], "has_completed": False}
                for r in data["recipients"]
            ]
            return httpx.Response(201, json={"id": doc_id, "status": "document.uploaded"})
        doc_id = path.split("/")[4]
        doc = self.documents[doc_id]
        if path.endswith("/session"):
            body = json.loads(request.content)
            self.sessions.append((doc_id, body["recipient"]))
            return httpx.Response(201, json={"id": f"sess-{doc_id}", "expires_at": "x"})
        if path.endswith("/fields"):
            assert doc["status"] == "document.draft"
            self.fields.append((doc_id, json.loads(request.content)["fields"]))
            return httpx.Response(201, json={"fields": []})
        if path.endswith("/send"):
            assert doc["status"] == "document.draft"
            doc["status"] = "document.sent"
            self.sent.append((doc_id, json.loads(request.content)))
            return httpx.Response(200, json={"id": doc_id, "status": "document.sent"})
        if path.endswith("/details"):
            return httpx.Response(
                200,
                json={
                    "id": doc_id,
                    "status": doc["status"],
                    "recipients": doc.get("recipients", []),
                },
            )
        if path.endswith("/download"):
            return httpx.Response(200, content=b"%PDF signed copy")
        if path.endswith("/download-protected"):
            return httpx.Response(401, json={"detail": "Production key only"})
        # status
        if doc["status"] == "document.uploaded":
            doc["polls"] += 1
            if doc["polls"] > self.polls_until_draft:
                doc["status"] = "document.draft"
        return httpx.Response(200, json={"id": doc_id, "status": doc["status"]})


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakePandaDoc]:
    fake = FakePandaDoc()
    monkeypatch.setattr(get_settings(), "pandadoc_api_key", SecretStr("test-key"))
    monkeypatch.setattr(get_settings(), "pandadoc_webhook_key", SecretStr(WEBHOOK_KEY))
    monkeypatch.setattr(pandadoc, "transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(service, "POLL_SECONDS", 0)
    yield fake


async def _person(make_user: MakeUser, signed_in_client: ClientFactory, email: str) -> AsyncClient:
    return await signed_in_client(await make_user(email, UserRole.AR_SPECIALIST))


async def _template(c: AsyncClient, name: str = "NDA", **form: str | int | float) -> dict[str, Any]:
    r = await c.post(
        "/api/v1/esign/templates",
        data={"name": name, **{k: str(v) for k, v in form.items()}},
        files={"file": ("nda.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


async def _send(c: AsyncClient, template_id: str, *emails: str) -> dict[str, Any]:
    r = await c.post(
        "/api/v1/esign/documents",
        json={
            "template_id": template_id,
            "subject": "Please sign",
            "message": "Thanks!",
            "recipients": [{"email": e, "first_name": "Jane", "last_name": "Doe"} for e in emails],
        },
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def _signed(events: list[dict[str, Any]]) -> tuple[bytes, str]:
    body = json.dumps(events).encode()
    return body, hmac.new(WEBHOOK_KEY.encode(), body, hashlib.sha256).hexdigest()


async def _webhook(c: AsyncClient, events: list[dict[str, Any]], **headers: str) -> httpx.Response:
    body, signature = _signed(events)
    return await c.post(
        f"/api/v1/esign/webhook?signature={signature}",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )


async def test_upload_send_and_follow_to_signed(
    fake: FakePandaDoc,
    client: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
) -> None:
    me = await _person(make_user, signed_in_client, "me@example.com")
    template = await _template(me)
    doc = await _send(me, template["id"], "Jane@Client.example", "cfo@client.example")

    # Uploaded with one role per signer, waited for draft, then emailed by PandaDoc
    assert fake.uploads[0]["recipients"][0] == {
        "email": "jane@client.example",
        "first_name": "Jane",
        "last_name": "Doe",
        "role": "signer1",
    }
    assert fake.uploads[0]["recipients"][1]["role"] == "signer2"
    assert fake.sent == [("pd1", {"silent": False, "subject": "Please sign", "message": "Thanks!"})]
    assert (doc["status"], doc["stage"], doc["send_pending"]) == ("document.sent", "sent", False)

    # PandaDoc's webhooks: viewed, one signer done, completed
    r = await _webhook(
        client,
        [
            {"event": "document_state_changed", "data": {"id": "pd1", "status": "document.viewed"}},
            {
                "event": "recipient_completed",
                "data": {
                    "id": "pd1",
                    "status": "document.viewed",
                    "action_by": {"email": "jane@client.example"},
                    "action_date": "2026-11-17T10:00:00Z",
                },
            },
        ],
        **{"X-PandaDoc-Webhook-Event-Id": "delivery-1"},
    )
    assert r.json() == {"applied": 2}
    # The same delivery again (PandaDoc retries): applied once only
    r = await _webhook(
        client,
        [{"event": "document_state_changed", "data": {"id": "pd1", "status": "document.voided"}}],
        **{"X-PandaDoc-Webhook-Event-Id": "delivery-1"},
    )
    assert r.json() == {"applied": 0}
    await _webhook(
        client,
        [
            {
                "event": "document_state_changed",
                "data": {"id": "pd1", "status": "document.completed"},
            }
        ],
    )
    # A late "viewed" can't move a completed document back
    await _webhook(
        client,
        [{"event": "document_state_changed", "data": {"id": "pd1", "status": "document.viewed"}}],
    )

    detail = (await me.get(f"/api/v1/esign/documents/{doc['id']}")).json()
    assert (detail["status"], detail["stage"]) == ("document.completed", "completed")
    assert detail["completed_at"] and detail["viewed_at"] and detail["sent_at"]
    assert [r["has_completed"] for r in detail["recipients"]] == [True, False]
    assert [e["event"] for e in detail["events"]][:4] == [
        "created",
        "fields_added",
        "sent",
        "document_state_changed",
    ]

    report = (await me.get("/api/v1/esign/report")).json()
    assert report["total"] == 1 and report["completion_rate"] == 1.0
    assert report["templates"] == [{"template_name": "NDA", "sent": 1, "completed": 1}]

    # The signed copy (a sandbox key can't read the e-vault: the plain download)
    r = await me.get(f"/api/v1/esign/documents/{doc['id']}/download")
    assert r.status_code == 200 and r.content == b"%PDF signed copy"
    assert "NDA (signed).pdf" in r.headers["content-disposition"]


async def test_only_the_sender_sees_their_documents(
    fake: FakePandaDoc, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    me = await _person(make_user, signed_in_client, "me@example.com")
    other = await _person(make_user, signed_in_client, "other@example.com")
    admin = await signed_in_client(await make_user("boss@example.com", UserRole.FINANCE_ADMIN))
    template = await _template(me)
    doc = await _send(me, template["id"], "jane@client.example")

    for c in (other, admin):  # a Finance Admin included
        assert (await c.get("/api/v1/esign/templates")).json() == []
        assert (await c.get("/api/v1/esign/documents")).json() == {"items": [], "total": 0}
        assert (await c.get("/api/v1/esign/report")).json()["total"] == 0
        assert (await c.get(f"/api/v1/esign/documents/{doc['id']}")).status_code == 404
        assert (await c.get(f"/api/v1/esign/documents/{doc['id']}/download")).status_code == 404
        r = await c.post(
            "/api/v1/esign/documents",
            json={
                "template_id": template["id"],
                "recipients": [{"email": "x@y.example", "first_name": "X"}],
            },
        )
        assert r.status_code == 404
        assert (await c.delete(f"/api/v1/esign/templates/{template['id']}")).status_code == 404
    assert len(fake.uploads) == 1

    page = (await me.get("/api/v1/esign/documents", params={"search": "jane@"})).json()
    assert page["total"] == 1
    assert (await me.get("/api/v1/esign/documents", params={"stage": "completed"})).json()[
        "total"
    ] == 0


async def test_slow_processing_is_sent_by_the_webhook(
    fake: FakePandaDoc,
    client: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
) -> None:
    fake.polls_until_draft = 10_000  # PandaDoc never says draft while the request waits
    me = await _person(make_user, signed_in_client, "me@example.com")
    doc = await _send(me, (await _template(me))["id"], "jane@client.example")
    assert doc["send_pending"] and doc["status_label"] == "Sending"
    assert fake.sent == []

    fake.documents["pd1"]["status"] = "document.draft"
    await _webhook(
        client,
        [{"event": "document_state_changed", "data": {"id": "pd1", "status": "document.draft"}}],
    )
    detail = (await me.get(f"/api/v1/esign/documents/{doc['id']}")).json()
    assert (detail["status"], detail["send_pending"]) == ("document.sent", False)
    assert len(fake.sent) == 1


async def test_refresh_reads_the_status_from_pandadoc(
    fake: FakePandaDoc, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    me = await _person(make_user, signed_in_client, "me@example.com")
    doc = await _send(me, (await _template(me))["id"], "jane@client.example")
    fake.documents["pd1"].update(
        status="document.completed",
        recipients=[{"email": "jane@client.example", "has_completed": True}],
    )
    detail = (await me.post(f"/api/v1/esign/documents/{doc['id']}/refresh")).json()
    assert detail["stage"] == "completed"
    assert detail["recipients"][0]["has_completed"] is True


async def test_webhooks_need_the_signature(fake: FakePandaDoc, client: AsyncClient) -> None:
    body, _ = _signed([{"event": "document_state_changed", "data": {"id": "pd1"}}])
    r = await client.post("/api/v1/esign/webhook?signature=forged", content=body)
    assert r.status_code == 401
    r = await client.post("/api/v1/esign/webhook", content=body)
    assert r.status_code == 401
    # A document this app didn't send: ignored
    r = await _webhook(
        client,
        [{"event": "document_state_changed", "data": {"id": "nope", "status": "document.sent"}}],
    )
    assert r.json() == {"applied": 0}


async def test_templates_are_checked_and_pandadoc_errors_shown(
    fake: FakePandaDoc, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    me = await _person(make_user, signed_in_client, "me@example.com")
    r = await me.post(
        "/api/v1/esign/templates",
        data={"name": "Bad"},
        files={"file": ("a.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == 422
    template = await _template(me)
    fake.refuse_upload = "One of field tags in PDF with type='signature' doesn't have a role"
    r = await me.post(
        "/api/v1/esign/documents",
        json={
            "template_id": template["id"],
            "recipients": [{"email": "a@b.example", "first_name": "A"}],
        },
    )
    assert r.status_code == 502
    assert "doesn't have a role" in r.json()["detail"]["message"]
    assert (await me.get("/api/v1/esign/documents")).json()["total"] == 0

    # Deleting a template keeps what was sent from it
    fake.refuse_upload = None
    await _send(me, template["id"], "a@b.example")
    assert (await me.delete(f"/api/v1/esign/templates/{template['id']}")).status_code == 204
    items = (await me.get("/api/v1/esign/documents")).json()["items"]
    assert items[0]["template_name"] == "NDA" and items[0]["template_id"] is None


async def test_not_configured(
    make_user: MakeUser, signed_in_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "pandadoc_api_key", None)  # whatever .env says
    me = await _person(make_user, signed_in_client, "me@example.com")
    setup = (await me.get("/api/v1/esign/setup")).json()
    assert setup["configured"] is False
    assert setup["webhook_url"].endswith("/api/v1/esign/webhook")
    template = await _template(me)
    r = await me.post(
        "/api/v1/esign/documents",
        json={
            "template_id": template["id"],
            "recipients": [{"email": "a@b.example", "first_name": "A"}],
        },
    )
    assert r.status_code == 503


async def test_signature_boxes_go_where_the_template_says(
    fake: FakePandaDoc,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "pandadoc_signature_x", 72.0)
    me = await _person(make_user, signed_in_client, "me@example.com")

    # The server's default position (PANDADOC_SIGNATURE_*), with the page chosen at upload
    default = await _template(me, "Default", page=2)
    assert default["signature_layout"] == {
        "page": 2,
        "x": 72.0,
        "y": 100.0,
        "width": 200.0,
        "height": 50.0,
    }
    await _send(me, default["id"], "a@client.example", "b@client.example")
    doc_id, fields = fake.fields[0]
    # One box per signer, assigned to them; the second one below the first
    assert [f["assigned_to"] for f in fields] == ["r-signer1", "r-signer2"]
    assert all(f["type"] == "signature" and f["layout"]["page"] == 2 for f in fields)
    assert [f["layout"]["position"]["offset_y"] for f in fields] == [100.0, 170.0]
    assert fields[0]["layout"]["style"] == {"width": 200.0, "height": 50.0}
    assert fake.sent[0][0] == doc_id  # boxes first, then sent

    # Field tags in the file: no boxes are added
    tagged = await _template(me, "Tagged", placement="tags")
    assert tagged["signature_layout"] is None
    await _send(me, tagged["id"], "a@client.example")
    assert len(fake.fields) == 1 and len(fake.sent) == 2

    r = await me.post(
        "/api/v1/esign/templates",
        data={"name": "Bad", "page": "0"},
        files={"file": ("nda.pdf", PDF, "application/pdf")},
    )
    assert r.status_code == 422


def _tagged_pdf(*lines: str) -> bytes:
    return render_pdf([(line, 11, False) for line in lines])


def _tagged_docx(*lines: str) -> bytes:
    document = Document()
    for line in lines:
        document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


async def test_dynamic_fields_are_found_and_filled_in_when_sending(
    fake: FakePandaDoc, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    me = await _person(make_user, signed_in_client, "me@example.com")
    pdf = _tagged_pdf(
        "Mutual NDA between {textfield:signer1:company___________} and Acme",
        "Effective {date:signer1:effective-date___}   Term (years) {t*:signer1:term___}",
        "Signed {signature:signer1___} {date:signer1}",
        "Signed {s:signer2___}",
    )
    r = await me.post(
        "/api/v1/esign/templates",
        data={"name": "NDA"},  # placement "position" by default: the tags win
        files={"file": ("nda.pdf", pdf, "application/pdf")},
    )
    assert r.status_code == 201, r.text
    template = r.json()
    assert template["signature_layout"] is None
    assert template["signers_needed"] == 2
    fillable = [t["id"] for t in template["field_tags"] if t["prefillable"]]
    assert fillable == ["company", "effective-date", "term"]
    term = next(t for t in template["field_tags"] if t["id"] == "term")
    assert (term["type"], term["required"]) == ("textfield", False)

    send = {
        "template_id": template["id"],
        "recipients": [{"email": "a@client.example", "first_name": "A"}],
    }
    r = await me.post("/api/v1/esign/documents", json=send)
    assert r.status_code == 422 and "2 signers" in r.json()["detail"]["message"]
    send["recipients"].append({"email": "b@client.example", "first_name": "B"})
    for bad in ({"nope": "x"}, {"effective-date": "17/11/2026"}):
        r = await me.post("/api/v1/esign/documents", json={**send, "values": bad})
        assert r.status_code == 422, bad
    assert fake.uploads == []

    values = {"company": "Globex Ltd", "effective-date": "2026-12-01", "term": " "}
    doc = (await me.post("/api/v1/esign/documents", json={**send, "values": values})).json()
    # Every tag id is declared (PandaDoc refuses the file otherwise); empty: the signer's
    assert fake.uploads[0]["fields"] == {
        "company": {"value": "Globex Ltd", "role": "signer1"},
        "effective-date": {"value": "2026-12-01T00:00:00.000Z", "role": "signer1"},
        "term": {"value": "", "role": "signer1"},
    }
    assert fake.fields == []  # no extra signature boxes: the file has its own
    detail = (await me.get(f"/api/v1/esign/documents/{doc['id']}")).json()
    assert detail["field_values"] == {"company": "Globex Ltd", "effective-date": "2026-12-01"}


async def test_word_templates_and_tag_mistakes(
    fake: FakePandaDoc, make_user: MakeUser, signed_in_client: ClientFactory
) -> None:
    me = await _person(make_user, signed_in_client, "me@example.com")
    docx = _tagged_docx("Client: {textfield:signer1:client___}", "Fee {c:signer1:agree}")
    r = await me.post(
        "/api/v1/esign/templates",
        data={"name": "Engagement"},
        files={"file": ("letter.docx", docx, "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert [t["id"] for t in body["field_tags"]] == ["client", "agree"]
    # No signature tag: the signature box goes at the fixed position
    assert body["signature_layout"] is not None

    r = await me.post(
        "/api/v1/esign/templates",
        data={"name": "Bad"},
        files={"file": ("bad.pdf", _tagged_pdf("{signature:Client___}"), "application/pdf")},
    )
    assert r.status_code == 422 and "signer1" in r.json()["detail"]["message"]


async def test_countersign_after_the_other_signers(
    fake: FakePandaDoc,
    client: AsyncClient,
    make_user: MakeUser,
    signed_in_client: ClientFactory,
) -> None:
    me = await _person(make_user, signed_in_client, "aman.sender@example.com")
    nda = _tagged_pdf("Client {signature:signer1___}", "Company {signature:signer2___}")
    r = await me.post(
        "/api/v1/esign/templates",
        data={"name": "NDA"},
        files={"file": ("nda.pdf", nda, "application/pdf")},
    )
    template = r.json()
    send = {
        "template_id": template["id"],
        "recipients": [{"email": "jane@client.example", "first_name": "Jane"}],
        "countersign": True,
    }
    # Already a signer yourself: refused (you're added as the last one)
    mine = {"email": "Aman.Sender@example.com", "first_name": "Me"}
    r = await me.post("/api/v1/esign/documents", json={**send, "recipients": [mine]})
    assert r.status_code == 422

    doc = (await me.post("/api/v1/esign/documents", json=send)).json()
    # The client signs first, the sender (signer2 of the template) after
    assert [(r["email"], r["role"], r["signing_order"]) for r in fake.uploads[0]["recipients"]] == [
        ("jane@client.example", "signer1", 1),
        ("aman.sender@example.com", "signer2", 2),
    ]
    assert doc["countersign"] is True and doc["your_turn"] is False
    assert doc["recipients"][1]["countersigner"] is True

    # Too early: the client hasn't signed (PandaDoc is asked first, it says the same)
    r = await me.post(f"/api/v1/esign/documents/{doc['id']}/countersign")
    assert r.status_code == 409 and "Not your turn" in r.json()["detail"]["message"]

    await _webhook(
        client,
        [
            {
                "event": "recipient_completed",
                "data": {
                    "id": "pd1",
                    "status": "document.viewed",
                    "action_by": {"email": "jane@client.example"},
                },
            }
        ],
    )
    page = (await me.get("/api/v1/esign/documents")).json()
    assert page["items"][0]["your_turn"] is True
    assert (await me.get("/api/v1/esign/report")).json()["awaiting_you"] == 1

    r = await me.post(f"/api/v1/esign/documents/{doc['id']}/countersign")
    assert r.status_code == 200, r.text
    assert r.json()["url"] == "https://app.pandadoc.com/s/sess-pd1/"
    assert fake.sessions == [("pd1", "aman.sender@example.com")]

    # Nobody else can open it
    other = await _person(make_user, signed_in_client, "other@example.com")
    assert (await other.post(f"/api/v1/esign/documents/{doc['id']}/countersign")).status_code == 404

    # Signed: done
    await _webhook(
        client,
        [
            {
                "event": "document_state_changed",
                "data": {"id": "pd1", "status": "document.completed"},
            }
        ],
    )
    assert (await me.get("/api/v1/esign/report")).json()["awaiting_you"] == 0
