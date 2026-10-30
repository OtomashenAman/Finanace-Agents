import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from src.app.service_pod.core.messaging.models import (
    ArtifactKind,
    ArtifactStatus,
    Audience,
    Direction,
    MessageStatus,
)


class MessageOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    direction: Direction
    audience: Audience | None
    purpose: str
    status: MessageStatus
    version: int
    to_email: str
    to_name: str | None
    from_email: str | None
    subject: str
    body: str
    artifact_ids: list[uuid.UUID]
    fact_block: str | None
    approval_checks: dict[str, bool] | None
    extraction: dict[str, Any] | None
    extraction_status: str | None
    approved_by: str | None
    approved_at: datetime | None
    provider: str | None
    sender: str | None
    simulated: bool
    provider_message_id: str | None
    sent_at: datetime | None
    error: str | None
    internet_message_id: str | None
    in_reply_to_id: uuid.UUID | None
    thread_evidence: str | None
    received_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class _MessageFields(BaseModel):
    audience: Audience
    purpose: str = Field(pattern=r"^[a-z][a-z_]{2,49}$")
    to_email: EmailStr
    to_name: str | None = Field(default=None, max_length=200)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20_000)
    artifact_ids: list[uuid.UUID] = Field(default=[], max_length=10)


class MessageDraftIn(_MessageFields):
    pass


class MessageUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    to_email: EmailStr | None = None
    to_name: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=20_000)
    artifact_ids: list[uuid.UUID] | None = Field(default=None, max_length=10)


class MessageVersion(BaseModel):
    expected_version: int = Field(ge=1)


class ApprovalChecks(BaseModel):
    """What is confirmed before customer mail is sent."""

    recipient: bool = False  # the address is the customer's verified contact
    mapping: bool = False  # the invoices and amounts are the right ones for this customer
    tone: bool = False  # the wording is appropriate

    @property
    def all_confirmed(self) -> bool:
        return self.recipient and self.mapping and self.tone


class MessageSend(MessageVersion):
    checks: ApprovalChecks = ApprovalChecks()


class ComposeRequest(BaseModel):
    purpose: str = Field(pattern=r"^[a-z][a-z_]{2,49}$")


class MessageReconcile(BaseModel):
    """After checking the provider's log for a send whose outcome was unknown."""

    expected_version: int = Field(ge=1)
    outcome: Literal["sent", "send_failed"]
    provider_message_id: str | None = Field(default=None, max_length=255)
    note: str = Field(min_length=5, max_length=1000)


class ReplyImport(BaseModel):
    """Either the original email file (.eml text, preferred: its headers prove the thread)
    or the reply pasted by hand together with the message it answers."""

    raw_eml: str | None = Field(default=None, max_length=2_000_000)
    from_email: EmailStr | None = None
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=100_000)
    reply_to_message_id: uuid.UUID | None = None  # required when pasted

    @model_validator(mode="after")
    def _one_form(self) -> "ReplyImport":
        pasted = self.from_email and self.body
        if bool(self.raw_eml) == bool(pasted):
            raise ValueError("Send either raw_eml or from_email + body (not both).")
        if pasted and self.reply_to_message_id is None:
            raise ValueError("A pasted reply must name the message it answers.")
        return self


class ArtifactOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    kind: ArtifactKind
    invoice_refs: list[str]
    filename: str
    content_type: str
    size: int
    sha256: str
    status: ArtifactStatus
    uploaded_by: str
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime


class ArtifactDecision(BaseModel):
    decision: Literal["approved", "rejected"]


class EmailStatus(BaseModel):
    provider: str
    simulated: bool  # outbox: approved messages are recorded, never sent
    sender: str | None
    ready: bool
    problem: str | None
    internal_recipients: list[str]
