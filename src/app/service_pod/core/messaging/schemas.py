import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

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
    case_reference: str
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
    invoice_numbers: list[str] | None  # only some of the case's invoices (None: all)
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
    created_by: str | None  # None: read from the mailbox by the worker
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


# The invoices an email is about, when only some of the case's (None: all of them)
InvoiceNumbers = Annotated[list[str], Field(min_length=1)] | None


class MessageDraftIn(_MessageFields):
    invoice_numbers: InvoiceNumbers = None


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

    recipient: bool = False  # the address is the right contact at the customer
    mapping: bool = False  # the invoices and amounts are the right ones for this customer
    tone: bool = False  # the wording is appropriate

    @property
    def all_confirmed(self) -> bool:
        return self.recipient and self.mapping and self.tone


class MessageSend(MessageVersion):
    checks: ApprovalChecks = ApprovalChecks()


class ComposeRequest(BaseModel):
    purpose: str = Field(pattern=r"^[a-z][a-z_]{2,49}$")
    invoice_numbers: InvoiceNumbers = None


class AssistRequest(BaseModel):
    """Ask the AI in plain English to write or change the draft (tone, length, content)."""

    purpose: str = Field(pattern=r"^[a-z][a-z_]{2,49}$")
    invoice_numbers: InvoiceNumbers = None
    instruction: str = Field(min_length=2, max_length=2000)
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=50_000)  # empty: write a new one


class AssistOut(BaseModel):
    subject: str
    body: str


class TemplateIn(BaseModel):
    """The draft as the customer's template; its invoice table and numbers become
    placeholders, filled in for each case."""

    purpose: str = Field(pattern=r"^[a-z][a-z_]{2,49}$")
    invoice_numbers: InvoiceNumbers = None
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50_000)


class TemplateOut(BaseModel):
    customer_name: str
    subject: str
    body: str
    updated_by: str | None
    updated_at: datetime


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
    test_recipient: str | None  # set: every email goes here instead (test mode)
