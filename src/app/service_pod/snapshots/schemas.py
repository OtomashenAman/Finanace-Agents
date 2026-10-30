import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.entities.schemas import EntityRef
from src.app.service_pod.snapshots.contract import Basis, Collection, Provenance
from src.app.service_pod.snapshots.models import SourceType


class SnapshotSummary(BaseModel):
    id: uuid.UUID
    entity: EntityRef
    parent_id: uuid.UUID | None
    source_type: SourceType
    provenance: Provenance
    is_demo: bool
    company_id: str
    company_name: str
    currency: str
    basis: Basis
    as_of: date
    source_reference: str
    sha256: str
    coverage: list[Collection]
    row_counts: dict[str, int]
    imported_by: str  # name
    imported_at: datetime


class SnapshotImportResult(BaseModel):
    snapshot: SnapshotSummary
    created: bool  # False: identical content was already imported (existing snapshot)


class QuickBooksSnapshotRequest(BaseModel):
    data_source_id: uuid.UUID
    entity_id: uuid.UUID
    currency: str = Field(pattern=r"^[A-Z]{3}$")  # the company's home currency
    basis: Basis


class SnapshotRows(BaseModel):
    collection: Collection
    rows: list[dict[str, Any]]
