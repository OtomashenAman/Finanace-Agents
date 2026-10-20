import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.data_sources.models import IntegrationEnvironment, SourceKind, SourceStatus
from src.app.data_sources.records import RecordType


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: SourceKind
    name: str
    status: SourceStatus
    # QuickBooks: the owner's own Intuit app (the secret is never returned)
    client_id: str | None
    environment: IntegrationEnvironment | None
    external_id: str | None
    last_synced_at: datetime | None
    last_error: str | None
    record_counts: dict[str, int]
    filename: str | None
    created_at: datetime
    updated_at: datetime


class SourceOwner(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class AdminDataSourceOut(DataSourceOut):
    """Admin overview: status only, never credentials or records."""

    owner: SourceOwner


class SourceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class QuickBooksApp(BaseModel):
    """The user's own Intuit app (Intuit Developer portal → Keys & OAuth)."""

    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=500)
    environment: IntegrationEnvironment


class QuickBooksAppUpdate(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    # Omit to keep the stored secret (it is never sent back to the browser)
    client_secret: str | None = Field(default=None, min_length=1, max_length=500)
    environment: IntegrationEnvironment


class RedirectUri(BaseModel):
    redirect_uri: str  # register exactly this in the Intuit app


class AuthorizeResponse(BaseModel):
    source: DataSourceOut
    url: str  # Intuit sign-in: send the browser here


class FieldSpec(BaseModel):
    name: str
    required: bool


class RecordTypeInfo(BaseModel):
    type: RecordType
    label: str
    fields: list[FieldSpec]


class UploadPreview(BaseModel):
    record_type: RecordType
    headers: list[str]
    mapping: dict[str, str | None]
    sample_rows: list[list[str]]
    row_count: int
    valid_count: int
    error_count: int
    errors: list[str]


class UploadResult(BaseModel):
    source: DataSourceOut
    imported: int
    skipped: int


class RecordOut(BaseModel):
    external_id: str
    record_type: RecordType
    reference: str
    counterparty: str | None
    amount: Decimal | None
    txn_date: date | None
    data: dict[str, Any]
