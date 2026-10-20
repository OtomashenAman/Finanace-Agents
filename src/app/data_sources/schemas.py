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


class QuickBooksStatus(BaseModel):
    configured: bool
    environment: IntegrationEnvironment | None


class AuthorizeRequest(BaseModel):
    """Omit source_id to connect a new company; pass it to re-authorize an existing one."""

    source_id: uuid.UUID | None = None


class AuthorizeResponse(BaseModel):
    url: str


class IntegrationAppOut(BaseModel):
    provider: SourceKind
    configured: bool
    client_id: str | None
    has_client_secret: bool
    environment: IntegrationEnvironment
    redirect_uri: str  # register exactly this in the Intuit app
    updated_at: datetime | None


class IntegrationAppUpdate(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    # Omit to keep the stored secret (it is never sent back to the browser)
    client_secret: str | None = Field(default=None, min_length=1, max_length=500)
    environment: IntegrationEnvironment


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
