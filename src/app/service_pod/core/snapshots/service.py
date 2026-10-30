"""Importing and reading immutable source snapshots."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.data_sources.models import DataSource, SourceKind
from src.app.entities import service as entities
from src.app.entities.models import LegalEntity
from src.app.entities.schemas import EntityRef
from src.app.service_pod.common.canonical import fingerprint, plain
from src.app.service_pod.core.access.exceptions import PodForbiddenError
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.snapshots import importers
from src.app.service_pod.core.snapshots.contract import (
    Basis,
    Collection,
    Provenance,
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import (
    DemoSnapshotNotAllowedError,
    SnapshotInvalidError,
    SnapshotNotFoundError,
)
from src.app.service_pod.core.snapshots.models import PodSnapshot, SourceType
from src.app.service_pod.core.snapshots.schemas import (
    QuickBooksSnapshotRequest,
    SnapshotImportResult,
    SnapshotRows,
    SnapshotSummary,
)


def document(snapshot: PodSnapshot) -> SnapshotDocument:
    return SnapshotDocument.model_validate(snapshot.payload)


async def _summaries(session: AsyncSession, snapshots: list[PodSnapshot]) -> list[SnapshotSummary]:
    entity_refs = await entities.refs(session, {s.entity_id for s in snapshots})
    names = dict(
        (
            await session.execute(
                select(User.id, User.full_name).where(
                    User.id.in_({s.imported_by for s in snapshots})
                )
            )
        ).all()
    )
    return [
        SnapshotSummary(
            id=s.id,
            entity=entity_refs[s.entity_id],
            parent_id=s.parent_id,
            source_type=s.source_type,
            provenance=s.provenance,
            is_demo=s.is_demo,
            company_id=s.company_id,
            company_name=s.company_name,
            currency=s.currency,
            basis=s.basis,
            as_of=s.as_of,
            source_reference=s.source_reference,
            sha256=s.sha256,
            coverage=[Collection(c) for c in s.coverage],
            row_counts=s.row_counts,
            imported_by=names.get(s.imported_by, "a deleted user"),
            imported_at=s.created_at,
        )
        for s in snapshots
    ]


async def summary(session: AsyncSession, snapshot: PodSnapshot) -> SnapshotSummary:
    return (await _summaries(session, [snapshot]))[0]


async def _entity(session: AsyncSession, access: PodAccess, entity_id: uuid.UUID) -> LegalEntity:
    access.require_entity(entity_id)
    entity = await session.get(LegalEntity, entity_id)
    if entity is None or not entity.is_active:
        raise SnapshotInvalidError("Unknown or inactive legal entity.")
    return entity


async def _store(
    session: AsyncSession,
    access: PodAccess,
    entity: LegalEntity,
    doc: SnapshotDocument,
    source_type: SourceType,
    ctx: RequestContext,
    parent: PodSnapshot | None = None,
) -> SnapshotImportResult:
    if doc.entity.upper() != entity.code.upper():
        raise SnapshotInvalidError(
            f"The export is for entity {doc.entity!r}, not {entity.code}. Import it into the "
            "legal entity it belongs to."
        )
    is_demo = doc.provenance == Provenance.SYNTHETIC_DEMO
    if is_demo and not get_settings().demo_snapshots_allowed:
        raise DemoSnapshotNotAllowedError
    payload = plain(doc)
    sha256 = fingerprint(payload)

    existing = await session.scalar(
        select(PodSnapshot).where(PodSnapshot.entity_id == entity.id, PodSnapshot.sha256 == sha256)
    )
    if existing is not None:
        return SnapshotImportResult(snapshot=await summary(session, existing), created=False)

    snapshot = PodSnapshot(
        entity_id=entity.id,
        parent_id=parent.id if parent else None,
        source_type=source_type,
        provenance=doc.provenance,
        is_demo=is_demo,
        company_id=doc.company_id,
        company_name=doc.company_name,
        entity_code=doc.entity,
        currency=doc.currency,
        basis=doc.basis,
        as_of=doc.as_of,
        source_reference=doc.source_reference,
        sha256=sha256,
        coverage=[c.value for c in doc.coverage],
        row_counts={c.value: doc.row_count(c) for c in doc.coverage},
        payload=payload,
        imported_by=access.user.id,
    )
    session.add(snapshot)
    await session.flush()
    record_event(
        session,
        "pod.snapshot_imported",
        ctx,
        actor_id=access.user.id,
        snapshot_id=str(snapshot.id),
        source_type=source_type.value,
        entity=entity.code,
        sha256=sha256,
        demo=is_demo,
        summary=(
            f"Imported a {source_type.value.replace('_', ' ')} snapshot of {doc.company_name} "
            f"({entity.code}, as of {doc.as_of.isoformat()})"
        ),
    )
    await session.commit()
    await session.refresh(snapshot)
    return SnapshotImportResult(snapshot=await summary(session, snapshot), created=True)


async def import_json(
    session: AsyncSession,
    access: PodAccess,
    entity_id: uuid.UUID,
    data: bytes,
    ctx: RequestContext,
) -> SnapshotImportResult:
    access.require_poster("import source data")
    entity = await _entity(session, access, entity_id)
    doc = importers.parse_json_export(data)
    return await _store(session, access, entity, doc, SourceType.JSON_EXPORT, ctx)


async def import_qbxml(
    session: AsyncSession,
    access: PodAccess,
    entity_id: uuid.UUID,
    data: bytes,
    filename: str,
    currency: str,
    basis: Basis,
    as_of: date,
    provenance: Provenance,
    ctx: RequestContext,
) -> SnapshotImportResult:
    access.require_poster("import source data")
    entity = await _entity(session, access, entity_id)
    doc = importers.parse_qbxml(
        data,
        entity_code=entity.code,
        currency=currency,
        basis=basis,
        as_of=as_of,
        provenance=provenance,
        filename=filename,
    )
    importers.check_row_limits(doc)
    return await _store(session, access, entity, doc, SourceType.QBXML, ctx)


async def import_quickbooks(
    session: AsyncSession, access: PodAccess, body: QuickBooksSnapshotRequest, ctx: RequestContext
) -> SnapshotImportResult:
    access.require_poster("import source data")
    entity = await _entity(session, access, body.entity_id)
    source = await session.get(DataSource, body.data_source_id)
    # Data sources are private to their owner, so only your own connection can be copied
    if source is None or source.owner_id != access.user.id:
        raise SnapshotNotFoundError("QuickBooks connection not found.")
    if source.kind != SourceKind.QUICKBOOKS or source.last_synced_at is None:
        raise SnapshotInvalidError("Choose a QuickBooks connection that has synced.")
    doc = await importers.from_quickbooks(session, source, entity.code, body.currency, body.basis)
    return await _store(session, access, entity, doc, SourceType.QUICKBOOKS_ONLINE, ctx)


async def get_visible(
    session: AsyncSession, access: PodAccess, snapshot_id: uuid.UUID
) -> PodSnapshot:
    snapshot = await session.get(PodSnapshot, snapshot_id)
    if snapshot is None or not access.can_see_entity(snapshot.entity_id):
        raise SnapshotNotFoundError
    if not (access.is_admin or access.is_poster or access.case_workflows):
        raise SnapshotNotFoundError
    return snapshot


async def import_bank_statement(
    session: AsyncSession,
    access: PodAccess,
    snapshot_id: uuid.UUID,
    data: bytes,
    ctx: RequestContext,
) -> SnapshotImportResult:
    """A new snapshot: the parent's content plus the statement's receipts. The parent stays
    exactly as it was."""
    access.require_poster("import bank statements")
    parent = await get_visible(session, access, snapshot_id)
    entity = await _entity(session, access, parent.entity_id)
    receipts = importers.parse_bank_csv(data)
    doc = importers.with_bank_receipts(document(parent), receipts)
    return await _store(session, access, entity, doc, SourceType.BANK_CSV, ctx, parent=parent)


async def list_snapshots(
    session: AsyncSession, access: PodAccess, entity_id: uuid.UUID | None
) -> list[SnapshotSummary]:
    if not (access.is_admin or access.is_poster or access.case_workflows):
        return []
    query = select(PodSnapshot).order_by(PodSnapshot.created_at.desc()).limit(200)
    if access.entity_ids is not None:
        query = query.where(PodSnapshot.entity_id.in_(access.entity_ids))
    if entity_id is not None:
        query = query.where(PodSnapshot.entity_id == entity_id)
    return await _summaries(session, list(await session.scalars(query)))


async def get_snapshot(
    session: AsyncSession, access: PodAccess, snapshot_id: uuid.UUID
) -> SnapshotSummary:
    return await summary(session, await get_visible(session, access, snapshot_id))


async def get_rows(
    session: AsyncSession, access: PodAccess, snapshot_id: uuid.UUID, collection: Collection
) -> SnapshotRows:
    snapshot = await get_visible(session, access, snapshot_id)
    if collection not in access.visible_collections:
        raise PodForbiddenError(f"Your roles don't include {collection.value} data.")
    value: Any = snapshot.payload.get(collection.value)
    rows = [] if value is None else value if isinstance(value, list) else [value]
    return SnapshotRows(collection=collection, rows=rows)


async def origin_type(session: AsyncSession, snapshot: PodSnapshot) -> SourceType:
    """Where the books came from: a bank statement snapshot takes its parent's type."""
    current: PodSnapshot | None = snapshot
    while current is not None and current.source_type == SourceType.BANK_CSV:
        current = await session.get(PodSnapshot, current.parent_id) if current.parent_id else None
    return current.source_type if current is not None else SourceType.BANK_CSV


async def entity_ref(session: AsyncSession, entity_id: uuid.UUID) -> EntityRef:
    return (await entities.refs(session, {entity_id}))[entity_id]
