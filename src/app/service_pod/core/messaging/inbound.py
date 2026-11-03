"""Reading an imported customer reply (.eml) without trusting more than its headers say."""

import email
import email.policy
import html
import re
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


# Reply prefixes mail apps put before a subject: Re, and AW / SV / Antw / R in some languages,
# possibly repeated and numbered ("RE[2]:")
_REPLY_PREFIX = re.compile(r"^\s*(re|aw|sv|antw|r)(\[\d+\])?\s*:\s*", re.IGNORECASE)


def answers_subject(reply_subject: str, sent_subject: str) -> bool:
    """Whether `reply_subject` is a reply to `sent_subject`: at least one reply prefix, then
    exactly that subject (case and spacing aside). For mail apps that send no In-Reply-To."""
    rest, prefixed = reply_subject, False
    while match := _REPLY_PREFIX.match(rest):
        rest, prefixed = rest[match.end() :], True

    def norm(text: str) -> str:
        return " ".join(text.split()).casefold()

    return prefixed and bool(norm(sent_subject)) and norm(rest) == norm(sent_subject)


def parse_eml(raw: str) -> ParsedReply:
    msg = email.message_from_string(raw, policy=email.policy.default)
    if not isinstance(msg, EmailMessage) or msg["From"] is None:
        raise ReplyInvalidError("This doesn't look like an email file (no From header).")
    from_email = parseaddr(str(msg["From"]))[1].strip().lower()
    if "@" not in from_email:
        raise ReplyInvalidError("The email's sender address can't be read.")
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        raise ReplyInvalidError("The email has no text to read.")
    body = str(part.get_content())
    if part.get_content_type() == "text/html":  # some mail apps send HTML only
        body = re.sub(r"<(style|script)\b.*?</\1>", " ", body, flags=re.S | re.I)
        body = re.sub(r"<br\s*/?>|</(p|div|tr|li)>", "\n", body, flags=re.I)
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))
        body = "\n".join(" ".join(line.split()) for line in body.splitlines())
        body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.strip()
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
