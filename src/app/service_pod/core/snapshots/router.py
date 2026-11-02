import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Form, Response, UploadFile, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.data_sources.models import DataSource
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.core.snapshots import purge, service, user_data
from src.app.service_pod.core.snapshots.contract import Basis, Collection, Provenance
from src.app.service_pod.core.snapshots.exceptions import (
    SnapshotNotFoundError,
    SnapshotTooLargeError,
)
from src.app.service_pod.core.snapshots.schemas import (
    ErpNextSnapshotRequest,
    PurgePreview,
    PurgeRequest,
    QuickBooksSnapshotRequest,
    SnapshotImportResult,
    SnapshotRemoval,
    SnapshotRows,
    SnapshotSummary,
    UserDataPreview,
    UserDataRemoval,
)

router = APIRouter(prefix="/snapshots", tags=["service pod: snapshots"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 413, 422)
}


async def _read(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise SnapshotTooLargeError(f"Files can be at most {limit // 1024} KB.")
    return data


def _status(result: SnapshotImportResult, response: Response) -> SnapshotImportResult:
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return result


@router.post("/json", response_model=SnapshotImportResult, responses=_ERRORS)
async def import_json(
    file: UploadFile,
    entity_id: Annotated[uuid.UUID, Form()],
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
) -> SnapshotImportResult:
    """Import a normalized read-only export (201; 200 when identical content exists)."""
    data = await _read(file, get_settings().pod_snapshot_max_bytes)
    return _status(await service.import_json(session, access, entity_id, data, ctx), response)


@router.post("/workbook", response_model=SnapshotImportResult, responses=_ERRORS)
async def import_workbook(
    file: UploadFile,
    entity_id: Annotated[uuid.UUID, Form()],
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
) -> SnapshotImportResult:
    """The normalized export as an Excel workbook: a Company sheet and one sheet per
    collection (see importers/workbook.py). 201; 200 when identical content exists."""
    data = await _read(file, get_settings().pod_snapshot_max_bytes)
    result = await service.import_workbook(
        session, access, entity_id, data, file.filename or "export.xlsx", ctx
    )
    return _status(result, response)


@router.post("/qbxml", response_model=SnapshotImportResult, responses=_ERRORS)
async def import_qbxml(
    file: UploadFile,
    entity_id: Annotated[uuid.UUID, Form()],
    currency: Annotated[str, Form(pattern=r"^[A-Z]{3}$")],
    basis: Annotated[Basis, Form()],
    as_of: Annotated[date, Form()],
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
    provenance: Annotated[Provenance, Form()] = Provenance.QUICKBOOKS_READONLY_EXPORT,
) -> SnapshotImportResult:
    """Import QuickBooks Desktop / Enterprise qbXML query responses (Company, Customer,
    Invoice, ReceivePayment, Account). The file doesn't state currency, basis or as-of date,
    so the importer does."""
    data = await _read(file, get_settings().pod_qbxml_max_bytes)
    result = await service.import_qbxml(
        session,
        access,
        entity_id,
        data,
        file.filename or "export.xml",
        currency,
        basis,
        as_of,
        provenance,
        ctx,
    )
    return _status(result, response)


@router.post("/erpnext", response_model=SnapshotImportResult, responses=_ERRORS)
async def import_erpnext(
    body: ErpNextSnapshotRequest,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
) -> SnapshotImportResult:
    """Freeze your connected ERPNext company's purchasing data into a snapshot (read only)."""
    return _status(await service.import_erpnext(session, access, body, ctx), response)


@router.post("/quickbooks", response_model=SnapshotImportResult, responses=_ERRORS)
async def import_quickbooks(
    body: QuickBooksSnapshotRequest,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
) -> SnapshotImportResult:
    """Freeze your connected QuickBooks company's synced records into a snapshot (read only)."""
    return _status(await service.import_quickbooks(session, access, body, ctx), response)


@router.post(
    "/{snapshot_id}/bank-statement", response_model=SnapshotImportResult, responses=_ERRORS
)
async def import_bank_statement(
    snapshot_id: uuid.UUID,
    file: UploadFile,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
    response: Response,
) -> SnapshotImportResult:
    """A new snapshot with the statement's receipts added; the original is unchanged."""
    data = await _read(file, get_settings().pod_bank_csv_max_bytes)
    result = await service.import_bank_statement(session, access, snapshot_id, data, ctx)
    return _status(result, response)


@router.get("", response_model=list[SnapshotSummary])
async def list_snapshots(
    session: SessionDep,
    _: PodAccessDep,
    entity_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> list[SnapshotSummary]:
    """Newest first; archived snapshots only when asked for."""
    return await service.list_snapshots(session, entity_id, include_archived)


@router.post("/{snapshot_id}/archive", response_model=SnapshotSummary, responses=_ERRORS)
async def archive_snapshot(
    snapshot_id: uuid.UUID,
    body: SnapshotRemoval,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> SnapshotSummary:
    """Take a snapshot out of use (hidden from lists and pickers, kept as evidence)."""
    return await service.archive_snapshot(session, access, snapshot_id, body.reason, ctx)


@router.post("/{snapshot_id}/restore", response_model=SnapshotSummary, responses=_ERRORS)
async def restore_snapshot(
    snapshot_id: uuid.UUID, session: SessionDep, access: PodAccessDep, ctx: RequestContextDep
) -> SnapshotSummary:
    return await service.restore_snapshot(session, access, snapshot_id, ctx)


@router.delete(
    "/{snapshot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_ERRORS,
)
async def delete_snapshot(
    snapshot_id: uuid.UUID,
    body: SnapshotRemoval,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> None:
    """Delete a snapshot nothing depends on (409 when a case, a verification or a later
    snapshot uses it: archive it instead)."""
    await service.delete_snapshot(session, access, snapshot_id, body.reason, ctx)


@router.get("/sources/{source_id}/dependents", response_model=PurgePreview, responses=_ERRORS)
async def data_source_dependents(
    source_id: uuid.UUID, session: SessionDep, access: PodAccessDep
) -> PurgePreview:
    """What deleting your data source "with dependents" would remove from the Service POD."""
    source = await session.get(DataSource, source_id)
    if source is None or source.owner_id != access.user.id:
        raise SnapshotNotFoundError("Data source not found.")
    return await purge.data_source_preview(session, source_id)


@router.get("/users/{user_id}/data", response_model=UserDataPreview, responses=_ERRORS)
async def user_data_preview(
    user_id: uuid.UUID, session: SessionDep, _: PodAccessDep
) -> UserDataPreview:
    """What removing this user's Service POD data would delete."""
    return await user_data.preview(session, user_id)


@router.post("/users/{user_id}/data/remove", response_model=UserDataPreview, responses=_ERRORS)
async def remove_user_data(
    user_id: uuid.UUID,
    body: UserDataRemoval,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> UserDataPreview:
    """Delete the user's data sources, imported snapshots and cases (with everything on them),
    then deactivate the user (kept: other records name them). Their email confirms it."""
    return await user_data.remove(session, access, user_id, body.reason, body.confirm, ctx)


@router.get("/{snapshot_id}/dependents", response_model=PurgePreview, responses=_ERRORS)
async def snapshot_dependents(
    snapshot_id: uuid.UUID, session: SessionDep, _: PodAccessDep
) -> PurgePreview:
    """What deleting this snapshot with everything on it would remove."""
    await service.load_snapshot(session, snapshot_id)
    return await purge.snapshot_preview(session, snapshot_id)


@router.post("/{snapshot_id}/purge", response_model=PurgePreview, responses=_ERRORS)
async def purge_snapshot(
    snapshot_id: uuid.UUID,
    body: PurgeRequest,
    session: SessionDep,
    access: PodAccessDep,
    ctx: RequestContextDep,
) -> PurgePreview:
    """Delete the snapshot, the snapshots built on it and every case on them (the company
    name must be typed to confirm). The audit trail keeps the record."""
    return await purge.purge_snapshot(session, access, snapshot_id, body.reason, body.confirm, ctx)


@router.get("/{snapshot_id}", response_model=SnapshotSummary, responses=_ERRORS)
async def get_snapshot(
    snapshot_id: uuid.UUID, session: SessionDep, _: PodAccessDep
) -> SnapshotSummary:
    return await service.get_snapshot(session, snapshot_id)


@router.get("/{snapshot_id}/rows", response_model=SnapshotRows, responses=_ERRORS)
async def get_rows(
    snapshot_id: uuid.UUID, collection: Collection, session: SessionDep, _: PodAccessDep
) -> SnapshotRows:
    """One collection's rows."""
    return await service.get_rows(session, snapshot_id, collection)
