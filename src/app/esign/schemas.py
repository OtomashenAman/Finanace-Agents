import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Stage(StrEnum):
    """PandaDoc's many statuses, grouped the way the report counts them."""

    PREPARING = "preparing"  # uploaded / draft: not with the signers yet
    SENT = "sent"
    VIEWED = "viewed"
    COMPLETED = "completed"
    DECLINED = "declined"
    VOIDED = "voided"  # voided or expired
    FAILED = "failed"


_STAGES: dict[str, Stage] = {
    "document.uploaded": Stage.PREPARING,
    "document.draft": Stage.PREPARING,
    "document.sent": Stage.SENT,
    "document.waiting_approval": Stage.SENT,
    "document.approved": Stage.SENT,
    "document.external_review": Stage.SENT,
    "document.viewed": Stage.VIEWED,
    "document.waiting_pay": Stage.VIEWED,
    "document.paid": Stage.COMPLETED,
    "document.completed": Stage.COMPLETED,
    "document.declined": Stage.DECLINED,
    "document.rejected": Stage.DECLINED,
    "document.voided": Stage.VOIDED,
    "document.expired": Stage.VOIDED,
    "document.error": Stage.FAILED,
    "failed": Stage.FAILED,
}

STATUS_LABELS: dict[str, str] = {
    "document.uploaded": "Preparing",
    "document.draft": "Draft",
    "document.sent": "Sent",
    "document.waiting_approval": "Waiting approval",
    "document.approved": "Approved",
    "document.external_review": "External review",
    "document.viewed": "Viewed",
    "document.waiting_pay": "Waiting payment",
    "document.paid": "Paid",
    "document.completed": "Completed",
    "document.declined": "Declined",
    "document.rejected": "Rejected",
    "document.voided": "Voided",
    "document.expired": "Expired",
    "document.error": "Error",
    "failed": "Failed",
}


def stage_of(status: str) -> Stage:
    return _STAGES.get(status, Stage.SENT)


def label_of(status: str) -> str:
    return STATUS_LABELS.get(status, status.removeprefix("document.").replace("_", " ").title())


class SignatureLayout(BaseModel):
    """A signature box: page (1-based), offsets from the top-left corner, size (points)."""

    page: int = Field(ge=1, le=500)
    x: float = Field(ge=0, le=5000)
    y: float = Field(ge=0, le=5000)
    width: float = Field(gt=0, le=2000)
    height: float = Field(gt=0, le=2000)


class EsignSetup(BaseModel):
    configured: bool  # API key set: documents can be sent
    webhook_configured: bool  # statuses arrive by themselves
    webhook_url: str  # paste into PandaDoc's webhook subscription
    max_bytes: int
    default_layout: SignatureLayout  # the server's PANDADOC_SIGNATURE_* position


class FieldTagOut(BaseModel):
    type: str  # textfield, date, checkbox, signature, initials...
    role: str  # signer1, signer2...
    id: str | None
    required: bool
    prefillable: bool  # has an id and a type the sender can fill in when sending


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    filename: str
    content_type: str
    size_bytes: int
    # None: the file has field tags
    signature_layout: SignatureLayout | None
    field_tags: list[FieldTagOut]
    signers_needed: int  # signer3 in a tag -> 3
    created_at: datetime
    times_sent: int = 0


class RecipientIn(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(default="", max_length=100)

    @field_validator("first_name", "last_name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class SendRequest(BaseModel):
    template_id: uuid.UUID
    name: str | None = Field(default=None, max_length=255)  # default: the template's name
    recipients: list[RecipientIn] = Field(min_length=1, max_length=10)
    subject: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=4000)
    # The template's dynamic fields, by tag id: text, a date (YYYY-MM-DD) or true/false
    values: dict[str, str] = Field(default_factory=dict, max_length=100)
    # Add the sender as the last signer: they get the document once every other signer has
    # signed, and sign it inside the app (a PandaDoc e-signature like any other)
    countersign: bool = False


class RecipientOut(BaseModel):
    email: str
    name: str
    role: str
    has_completed: bool = False
    completed_at: datetime | None = None
    countersigner: bool = False  # the sender, signing after everyone else


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event: str
    status: str | None
    recipient_email: str | None
    detail: str | None
    created_at: datetime


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    template_id: uuid.UUID | None
    template_name: str
    pandadoc_id: str | None
    status: str
    status_label: str
    stage: Stage
    send_pending: bool
    subject: str | None
    recipients: list[RecipientOut]
    countersign: bool  # the sender signs last
    your_turn: bool  # everyone else has signed: the sender's countersignature is due
    error: str | None
    created_at: datetime
    sent_at: datetime | None
    viewed_at: datetime | None
    completed_at: datetime | None
    status_changed_at: datetime | None


class DocumentDetail(DocumentOut):
    message: str | None
    field_values: dict[str, Any]
    events: list[EventOut]


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int


class SigningSession(BaseModel):
    session_id: str
    url: str  # embed in an iframe
    expires_in_seconds: int


class StageCount(BaseModel):
    stage: Stage
    count: int


class TemplateUsage(BaseModel):
    template_name: str
    sent: int
    completed: int


class EsignReport(BaseModel):
    """The sender's own documents only."""

    total: int
    by_stage: list[StageCount]
    completion_rate: float | None  # completed / (everything that reached the signers)
    avg_hours_to_complete: float | None
    awaiting_signature: int  # sent or viewed: someone still has to sign
    awaiting_you: int  # your countersignature is due
    sent_last_30_days: int
    completed_last_30_days: int
    templates: list[TemplateUsage]
