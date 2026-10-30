"""Email transports. A send either succeeds (the provider accepted the message), is refused
(nothing went out, safe to fix and approve again) or has an unknown outcome (a timeout:
it may have gone out, so a person checks the provider log instead of retrying)."""

import base64
import uuid
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from src.app.core.config import get_settings
from src.app.service_pod.core.messaging.graph import GraphError, GraphMailbox

BREVO_API = "https://api.brevo.com/v3"
GRAPH_ATTACHMENTS_MAX = 3 * 1024 * 1024  # Graph takes attachments up to 3 MB inline


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class OutgoingEmail:
    to_email: str
    to_name: str | None
    subject: str
    body: str
    sender: str
    sender_name: str
    attachments: list[Attachment] = field(default_factory=list)


class SendRefusedError(Exception):
    """The provider rejected the message: it was not sent."""


class SendUncertainError(Exception):
    """No clear answer (timeout, 5xx, network): it may or may not have been sent."""


class EmailProvider(Protocol):
    name: str
    simulated: bool  # True: nothing ever leaves the application

    @property
    def sender(self) -> str | None: ...

    async def readiness(self) -> str | None:
        """None when approved messages can be sent, else what's wrong. Never sends mail."""
        ...

    async def send(self, email: OutgoingEmail) -> str:
        """The provider's message ID, or SendRefusedError / SendUncertainError."""
        ...


class OutboxProvider:
    """Development and labelled demonstrations: records the message as sent, sends nothing."""

    name = "outbox"
    simulated = True

    def __init__(self, sender: str | None) -> None:
        self.sender = sender or "finance-outbox@localhost"

    async def readiness(self) -> str | None:
        return None

    async def send(self, email: OutgoingEmail) -> str:
        return f"<outbox-{uuid.uuid4()}@localhost>"


class BrevoProvider:
    name = "brevo"
    simulated = False

    def __init__(self, api_key: str, sender: str, timeout: float) -> None:
        self.sender = sender
        self._headers = {"api-key": api_key, "accept": "application/json"}
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=BREVO_API, headers=self._headers, timeout=self._timeout)

    async def readiness(self) -> str | None:
        try:
            async with self._client() as client:
                resp = await client.get("/senders")
        except httpx.HTTPError:
            return "Brevo can't be reached right now."
        if resp.status_code in (401, 403):
            return "Brevo refused the API key."
        if resp.status_code != 200:
            return f"Brevo answered {resp.status_code} when checking the sender."
        senders = resp.json().get("senders", [])
        match = next(
            (s for s in senders if s.get("email", "").lower() == self.sender.lower()), None
        )
        if match is None:
            return f"{self.sender} isn't a sender in this Brevo account."
        if not match.get("active", False):
            return f"The Brevo sender {self.sender} isn't verified / active."
        return None

    async def send(self, email: OutgoingEmail) -> str:
        body: dict[str, object] = {
            "sender": {"email": email.sender, "name": email.sender_name},
            "to": [{"email": email.to_email, **({"name": email.to_name} if email.to_name else {})}],
            "subject": email.subject,
            "textContent": email.body,
        }
        if email.attachments:
            body["attachment"] = [
                {"name": a.filename, "content": base64.b64encode(a.content).decode()}
                for a in email.attachments
            ]
        try:
            async with self._client() as client:
                resp = await client.post("/smtp/email", json=body)
        except httpx.TimeoutException as exc:
            raise SendUncertainError("Brevo didn't answer in time.") from exc
        except httpx.HTTPError as exc:
            raise SendUncertainError(f"Network error talking to Brevo: {exc}") from exc
        if resp.status_code >= 500:
            raise SendUncertainError(f"Brevo answered {resp.status_code}.")
        if resp.status_code >= 400:
            raise SendRefusedError(
                f"Brevo refused the message ({resp.status_code}): {resp.text[:300]}"
            )
        message_id = resp.json().get("messageId")
        if not message_id:
            raise SendUncertainError("Brevo accepted the request but returned no message ID.")
        return str(message_id)


class MicrosoftGraphProvider:
    """Sends as a Microsoft 365 mailbox. The message is first saved as a draft (nothing goes
    out, and Exchange gives it its Message-ID, which the customer's reply will quote), then
    sent; the sent mail stays in the mailbox's Sent Items."""

    name = "microsoft"
    simulated = False

    def __init__(self, mailbox: GraphMailbox, sender: str) -> None:
        self._mailbox = mailbox
        self.sender = sender

    async def readiness(self) -> str | None:
        try:
            await self._mailbox.token()
        except GraphError as exc:
            return str(exc)
        return None

    async def send(self, email: OutgoingEmail) -> str:
        if sum(len(a.content) for a in email.attachments) > GRAPH_ATTACHMENTS_MAX:
            raise SendRefusedError("Attachments over 3 MB in total can't be sent this way.")
        message: dict[str, object] = {
            "subject": email.subject,
            "body": {"contentType": "Text", "content": email.body},
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": email.to_email,
                        **({"name": email.to_name} if email.to_name else {}),
                    }
                }
            ],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a.filename,
                    "contentType": a.content_type,
                    "contentBytes": base64.b64encode(a.content).decode(),
                }
                for a in email.attachments
            ],
        }
        if email.sender.lower() != self._mailbox.mailbox.lower():
            message["from"] = {"emailAddress": {"address": email.sender, "name": email.sender_name}}
        try:
            draft = (await self._mailbox.request("POST", "/messages", json=message)).json()
        except GraphError as exc:
            # Only a draft was being saved: nothing can have gone out
            raise SendRefusedError(f"Microsoft didn't take the message: {exc}") from exc
        try:
            await self._mailbox.request("POST", f"/messages/{draft['id']}/send")
        except GraphError as exc:
            if exc.uncertain:
                raise SendUncertainError(f"{exc} Check the mailbox's Sent Items.") from exc
            raise SendRefusedError(f"Microsoft refused to send it: {exc}") from exc
        message_id = draft.get("internetMessageId")
        if not message_id:
            raise SendUncertainError(
                "Sent, but Microsoft returned no Message-ID: check Sent Items."
            )
        return str(message_id)


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    if settings.email_provider == "microsoft":
        mailbox = GraphMailbox.from_settings()
        return MicrosoftGraphProvider(mailbox, settings.email_sender or mailbox.mailbox)
    if settings.email_provider == "brevo":
        assert settings.brevo_api_key and settings.email_sender  # noqa: S101 - config validated
        return BrevoProvider(
            settings.brevo_api_key.get_secret_value(),
            settings.email_sender,
            settings.email_timeout_seconds,
        )
    return OutboxProvider(settings.email_sender)
