"""Importing and reading immutable source snapshots."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Select, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.core.config import get_settings
from src.app.data_sources import service as data_sources
from src.app.data_sources.exceptions import AppCredentialsError
from src.app.data_sources.models import DataSource, SourceKind
from src.app.data_sources.providers import quickbooks as qb
from src.app.entities import service as entities
from src.app.entities.models import LegalEntity
from src.app.entities.schemas import EntityRef
from src.app.service_pod.common.canonical import fingerprint, plain
from src.app.service_pod.common.people import DELETED, names
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.snapshots import importers
from src.app.service_pod.core.snapshots.contract import (
    Basis,
    Collection,
    Provenance,
    SnapshotDocument,
)
from src.app.service_pod.core.snapshots.exceptions import (
    DemoSnapshotNotAllowedError,
    SnapshotConflictError,
    SnapshotInvalidError,
    SnapshotNotFoundError,
)
from src.app.service_pod.core.snapshots.importers.quickbooks_pnl import PnlReports, fetch_pnl
from src.app.service_pod.core.snapshots.models import (
    PodSnapshot,
    PodSnapshotArchive,
    PodSnapshotSource,
    SourceType,
)
from src.app.service_pod.core.snapshots.schemas import (
    QuickBooksSnapshotRequest,
    SnapshotImportResult,
    SnapshotRows,
    SnapshotSummary,
)
from src.app.service_pod.core.tasks.models import PodPostingTask


def document(snapshot: PodSnapshot) -> SnapshotDocument:
    return SnapshotDocument.model_validate(snapshot.payload)


async def _counts(session: AsyncSession, column: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = await session.execute(
        select(column, func.count()).where(column.in_(ids)).group_by(column)
    )
    return dict(rows.all())


async def _summaries(session: AsyncSession, snapshots: list[PodSnapshot]) -> list[SnapshotSummary]:
    ids = [s.id for s in snapshots]
    entity_refs = await entities.refs(session, {s.entity_id for s in snapshots})
    archives = {
        a.snapshot_id: a
        for a in await session.scalars(
            select(PodSnapshotArchive).where(PodSnapshotArchive.snapshot_id.in_(ids))
        )
    }
    people = await names(
        session, [*(s.imported_by for s in snapshots), *(a.archived_by for a in archives.values())]
    )
    cases = await _counts(session, PodCase.snapshot_id, ids)
    proofs = await _counts(session, PodPostingTask.verification_snapshot_id, ids)
    children = await _counts(session, PodSnapshot.parent_id, ids)
    out = []
    for s in snapshots:
        archive = archives.get(s.id)
        uses = []
        if cases.get(s.id):
            uses.append(f"{cases[s.id]} case(s) use it")
        if proofs.get(s.id):
            uses.append("it verified a posting")
        if children.get(s.id):
            uses.append("a later snapshot extends it")
        out.append(
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
                imported_by=people.get(s.imported_by, DELETED),
                imported_at=s.created_at,
                used_by_cases=cases.get(s.id, 0),
                in_use="; ".join(uses) or None,
                archived=archive is not None,
                archived_reason=archive.reason if archive else None,
                archived_by=people.get(archive.archived_by, DELETED) if archive else None,
                archived_at=archive.created_at if archive else None,
            )
        )
    return out


async def summary(session: AsyncSession, snapshot: PodSnapshot) -> SnapshotSummary:
    return (await _summaries(session, [snapshot]))[0]


async def _entity(session: AsyncSession, entity_id: uuid.UUID) -> LegalEntity:
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
    entity = await _entity(session, entity_id)
    doc = importers.parse_json_export(data)
    return await _store(session, access, entity, doc, SourceType.JSON_EXPORT, ctx)


async def import_workbook(
    session: AsyncSession,
    access: PodAccess,
    entity_id: uuid.UUID,
    data: bytes,
    filename: str,
    ctx: RequestContext,
) -> SnapshotImportResult:
    """The same normalized export as JSON, as an Excel workbook (same source type, so a
    later export in either form can verify a posting)."""
    entity = await _entity(session, entity_id)
    doc = importers.parse_workbook(data, filename)
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
    entity = await _entity(session, entity_id)
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
    entity = await _entity(session, body.entity_id)
    source = await session.get(DataSource, body.data_source_id)
    # Data sources are private to their owner, so only your own connection can be copied
    if source is None or source.owner_id != access.user.id:
        raise SnapshotNotFoundError("QuickBooks connection not found.")
    if source.kind != SourceKind.QUICKBOOKS or source.last_synced_at is None:
        raise SnapshotInvalidError("Choose a QuickBooks connection that has synced.")
    notes: list[str] = []
    pnl = await _read_pnl(session, source, body.basis, notes)
    doc = await importers.from_quickbooks(
        session, source, entity.code, body.currency, body.basis, pnl=pnl, notes=notes
    )
    result = await _store(session, access, entity, doc, SourceType.QUICKBOOKS_ONLINE, ctx)
    result.notes = notes
    if await session.get(PodSnapshotSource, result.snapshot.id) is None:
        session.add(PodSnapshotSource(snapshot_id=result.snapshot.id, data_source_id=source.id))
        await session.commit()
    return result


async def _read_pnl(
    session: AsyncSession, source: DataSource, basis: Basis, notes: list[str]
) -> PnlReports | None:
    """The P&L by month and its detail (FP&A's evidence), read live from QuickBooks. If they
    can't be read the snapshot is still made, without GL lines and transactions."""
    try:
        async with data_sources.quickbooks_api(session, source) as api:
            return await fetch_pnl(api, utcnow().date(), basis)
    except (AppCredentialsError, qb.QuickBooksError) as exc:
        notes.append(f"P&L detail for FP&A couldn't be read from QuickBooks: {exc}")
        return None


async def load_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> PodSnapshot:
    snapshot = await session.get(PodSnapshot, snapshot_id)
    if snapshot is None:
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
    parent = await load_snapshot(session, snapshot_id)
    entity = await _entity(session, parent.entity_id)
    receipts = importers.parse_bank_csv(data)
    doc = importers.with_bank_receipts(document(parent), receipts)
    return await _store(session, access, entity, doc, SourceType.BANK_CSV, ctx, parent=parent)


def archived_ids() -> Select[tuple[uuid.UUID]]:
    return select(PodSnapshotArchive.snapshot_id)


async def list_snapshots(
    session: AsyncSession, entity_id: uuid.UUID | None, include_archived: bool = False
) -> list[SnapshotSummary]:
    query = select(PodSnapshot).order_by(PodSnapshot.created_at.desc()).limit(200)
    if not include_archived:
        query = query.where(PodSnapshot.id.not_in(archived_ids()))
    if entity_id is not None:
        query = query.where(PodSnapshot.entity_id == entity_id)
    return await _summaries(session, list(await session.scalars(query)))


async def get_snapshot(session: AsyncSession, snapshot_id: uuid.UUID) -> SnapshotSummary:
    return await summary(session, await load_snapshot(session, snapshot_id))


async def get_rows(
    session: AsyncSession, snapshot_id: uuid.UUID, collection: Collection
) -> SnapshotRows:
    snapshot = await load_snapshot(session, snapshot_id)
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


# --- taking a snapshot out of use ------------------------------------------------------


async def archive_snapshot(
    session: AsyncSession,
    access: PodAccess,
    snapshot_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> SnapshotSummary:
    """Hide a snapshot from lists and pickers; it stays as evidence and can be restored."""
    snapshot = await load_snapshot(session, snapshot_id)
    if await session.get(PodSnapshotArchive, snapshot.id) is not None:
        raise SnapshotConflictError("This snapshot is already archived.")
    session.add(
        PodSnapshotArchive(snapshot_id=snapshot.id, archived_by=access.user.id, reason=reason)
    )
    _event(
        session,
        "pod.snapshot_archived",
        ctx,
        access,
        snapshot,
        f"Archived the snapshot of {snapshot.company_name} as of {snapshot.as_of}: {reason}",
        reason=reason,
    )
    await session.commit()
    return await summary(session, snapshot)


async def restore_snapshot(
    session: AsyncSession, access: PodAccess, snapshot_id: uuid.UUID, ctx: RequestContext
) -> SnapshotSummary:
    snapshot = await load_snapshot(session, snapshot_id)
    archive = await session.get(PodSnapshotArchive, snapshot.id)
    if archive is None:
        raise SnapshotConflictError("This snapshot isn't archived.")
    await session.delete(archive)
    _event(
        session,
        "pod.snapshot_restored",
        ctx,
        access,
        snapshot,
        f"Restored the snapshot of {snapshot.company_name} as of {snapshot.as_of}",
    )
    await session.commit()
    return await summary(session, snapshot)


async def delete_snapshot(
    session: AsyncSession,
    access: PodAccess,
    snapshot_id: uuid.UUID,
    reason: str,
    ctx: RequestContext,
) -> None:
    """Remove a snapshot nothing depends on (no case, no verification, no later snapshot
    built on it), e.g. a wrong import. Anything used is evidence: archive it instead."""
    snapshot = await load_snapshot(session, snapshot_id)
    in_use = (await summary(session, snapshot)).in_use
    if in_use:
        raise SnapshotConflictError(
            f"This snapshot can't be deleted: {in_use}. Archive it instead."
        )
    _event(
        session,
        "pod.snapshot_deleted",
        ctx,
        access,
        snapshot,
        f"Deleted the unused snapshot of {snapshot.company_name} as of {snapshot.as_of}: {reason}",
        reason=reason,
        company=snapshot.company_name,
        as_of=snapshot.as_of.isoformat(),
    )
    # The database refuses deleting snapshots unless this transaction says it's this path
    await session.execute(text("SET LOCAL finance_acc.pod_snapshot_delete = 'on'"))
    await session.execute(delete(PodSnapshot).where(PodSnapshot.id == snapshot.id))
    await session.commit()


def _event(
    session: AsyncSession,
    event: str,
    ctx: RequestContext,
    access: PodAccess,
    snapshot: PodSnapshot,
    summary_text: str,
    **details: Any,
) -> None:
    record_event(
        session,
        event,
        ctx,
        actor_id=access.user.id,
        snapshot_id=str(snapshot.id),
        sha256=snapshot.sha256,
        summary=summary_text,
        **details,
    )
