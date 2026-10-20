import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)
from src.app.data_sources.records import RecordType


class SourceKind(StrEnum):
    QUICKBOOKS = "quickbooks"
    UPLOAD = "upload"


class SourceStatus(StrEnum):
    PENDING_AUTH = "pending_auth"  # created, waiting for the user to authorize
    CONNECTED = "connected"  # QuickBooks authorized
    NEEDS_REAUTH = "needs_reauth"  # refresh token expired or revoked
    ERROR = "error"  # last sync failed for another reason
    READY = "ready"  # upload imported


class IntegrationEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class IntegrationApp(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Organization-wide OAuth app (e.g. one Intuit app), set up once by a Finance Admin.

    Every user connects their own company through it; they never see these credentials.
    """

    __tablename__ = "integration_apps"
    __table_args__ = (
        enum_check("provider", SourceKind),
        enum_check("environment", IntegrationEnvironment),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    provider: Mapped[SourceKind] = mapped_column(string_enum(SourceKind, 32), unique=True)
    client_id: Mapped[str] = mapped_column(String(255))
    client_secret_enc: Mapped[str] = mapped_column(Text)
    environment: Mapped[IntegrationEnvironment] = mapped_column(
        string_enum(IntegrationEnvironment, 16)
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class DataSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One user's connected company or uploaded file. Visible to its owner only
    (admins see status, never credentials or records)."""

    __tablename__ = "data_sources"
    __table_args__ = (enum_check("kind", SourceKind), enum_check("status", SourceStatus))
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SourceKind] = mapped_column(string_enum(SourceKind, 32))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[SourceStatus] = mapped_column(string_enum(SourceStatus, 32))
    # QuickBooks: realmId (company id)
    external_id: Mapped[str | None] = mapped_column(String(100))
    # Encrypted JSON: {"refresh_token", "access_token", "access_expires_at"}
    credentials_enc: Mapped[str | None] = mapped_column(Text)
    # One-time value bound into the OAuth state; cleared when the callback consumes it
    oauth_nonce: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(String(500))
    record_counts: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    # Uploads: what was imported (the file itself is never stored)
    filename: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))


class FinanceRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A canonical record (see records.py) from one data source. Replaced on every sync."""

    __tablename__ = "finance_records"
    __table_args__ = (
        UniqueConstraint("source_id", "record_type", "external_id"),
        enum_check("record_type", RecordType),
        Index("ix_finance_records_lookup", "source_id", "record_type", "reference"),
    )

    # Indexed by ix_finance_records_lookup (source_id first)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"))
    record_type: Mapped[RecordType] = mapped_column(string_enum(RecordType, 32))
    external_id: Mapped[str] = mapped_column(String(100))
    reference: Mapped[str] = mapped_column(String(200))
    counterparty: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    txn_date: Mapped[date | None]
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
