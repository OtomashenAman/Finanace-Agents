import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.entities.schemas import EntityRef
from src.app.service_pod.core.snapshots.contract import Basis, Collection, Provenance
from src.app.service_pod.core.snapshots.models import SourceType


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
    used_by_cases: int
    # Why it can't be deleted (cases, a verified posting, a later snapshot built on it); None:
    # nothing depends on it
    in_use: str | None
    archived: bool
    archived_reason: str | None
    archived_by: str | None
    archived_at: datetime | None


class SnapshotImportResult(BaseModel):
    snapshot: SnapshotSummary
    created: bool  # False: identical content was already imported (existing snapshot)
    notes: list[str] = []  # what the import couldn't include, and why


class QuickBooksSnapshotRequest(BaseModel):
    data_source_id: uuid.UUID
    entity_id: uuid.UUID
    currency: str = Field(pattern=r"^[A-Z]{3}$")  # the company's home currency
    basis: Basis


class SnapshotRemoval(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class SnapshotRows(BaseModel):
    collection: Collection
    rows: list[dict[str, Any]]


# --- deleting a snapshot with everything that depends on it ------------------------------


class PurgeSnapshot(BaseModel):
    id: uuid.UUID
    company_name: str
    as_of: date
    source_type: str
    is_demo: bool


class PurgeCase(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    workflow: str
    status: str


class PurgePreview(BaseModel):
    """What a deletion removes (shown before it happens, returned after)."""

    snapshots: list[PurgeSnapshot]
    cases: list[PurgeCase]
    messages: int
    documents: int
    posting_tasks: int
    review_tasks: int
    commitments: int
    approvals: int
    verified_elsewhere: int  # postings of kept cases that lose their verifying snapshot
    evidence: bool  # real books with approved / completed work or verified postings
    all_demo: bool


class PurgeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    confirm: str = Field(min_length=1, max_length=200)  # the company name, typed


class UserDataPreview(PurgePreview):
    user_name: str
    data_sources: list[str]


class UserDataRemoval(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    confirm: str = Field(min_length=3, max_length=320)  # the user's email, typed
