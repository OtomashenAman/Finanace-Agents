"""Reading an imported customer reply (.eml) without trusting more than its headers say."""

import email
import email.policy
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

from src.app.core.errors import AppError


class ReplyInvalidError(AppError):
    status_code = 422
    code = "reply_invalid"


@dataclass(frozen=True)
class ParsedReply:
    from_email: str
    subject: str
    body: str
    message_id: str | None
    replies_to: list[str]  # In-Reply-To and References, normalized


def normalize_id(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith("<") else f"<{value}>"


def parse_eml(raw: str) -> ParsedReply:
    msg = email.message_from_string(raw, policy=email.policy.default)
    if not isinstance(msg, EmailMessage) or msg["From"] is None:
        raise ReplyInvalidError("This doesn't look like an email file (no From header).")
    from_email = parseaddr(str(msg["From"]))[1].strip().lower()
    if "@" not in from_email:
        raise ReplyInvalidError("The email's sender address can't be read.")
    part = msg.get_body(preferencelist=("plain",))
    if part is None:
        raise ReplyInvalidError("The email has no plain-text part to read.")
    body = str(part.get_content()).strip()
    if not body:
        raise ReplyInvalidError("The email is empty.")
    references = " ".join(str(msg.get(h, "")) for h in ("In-Reply-To", "References")).split()
    message_id = msg.get("Message-ID")
    return ParsedReply(
        from_email=from_email,
        subject=str(msg.get("Subject", "")),
        body=body,
        message_id=normalize_id(str(message_id)) if message_id else None,
        replies_to=[normalize_id(r) for r in references if r.strip()],
    )
