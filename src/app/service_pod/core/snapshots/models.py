import uuid
from datetime import date
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.app.common.models import (
    Base,
    CreatedAtMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    string_enum,
)
from src.app.service_pod.core.snapshots.contract import Basis, Provenance


class SourceType(StrEnum):
    JSON_EXPORT = "json_export"  # a normalized read-only export file
    BANK_CSV = "bank_csv"  # a bank statement added to an earlier snapshot (new snapshot)
    QUICKBOOKS_ONLINE = "quickbooks_online"  # frozen copy of a connected company's records
    QBXML = "qbxml"  # QuickBooks Desktop / Enterprise qbXML query responses


class PodSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable import of source data. A database trigger refuses UPDATE and DELETE;
    importing the same content again returns the existing row. created_at is the server
    import time that later verification compares against."""

    __tablename__ = "pod_snapshots"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config
    __table_args__ = (
        UniqueConstraint("entity_id", "sha256"),
        enum_check("source_type", SourceType),
        enum_check("basis", Basis),
        enum_check("provenance", Provenance),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_entities.id", ondelete="RESTRICT"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pod_snapshots.id", ondelete="RESTRICT")
    )
    source_type: Mapped[SourceType] = mapped_column(string_enum(SourceType, 32))
    provenance: Mapped[Provenance] = mapped_column(string_enum(Provenance, 32))
    is_demo: Mapped[bool]
    company_id: Mapped[str] = mapped_column(String(100))
    company_name: Mapped[str] = mapped_column(String(200))
    entity_code: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    basis: Mapped[Basis] = mapped_column(string_enum(Basis, 16))
    as_of: Mapped[date]
    source_reference: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))  # of the canonical JSON payload
    coverage: Mapped[list[str]] = mapped_column(JSONB)  # collections the source supplied
    row_counts: Mapped[dict[str, int]] = mapped_column(JSONB)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    imported_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class PodSnapshotArchive(CreatedAtMixin, Base):
    """A snapshot taken out of everyday use (e.g. imported with the wrong as-of date). The
    snapshot itself stays, unchanged, as evidence for the cases that used it; restoring it
    removes this row. created_at is when it was archived."""

    __tablename__ = "pod_snapshot_archives"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012 - SQLAlchemy class config

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pod_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    archived_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str] = mapped_column(Text)
