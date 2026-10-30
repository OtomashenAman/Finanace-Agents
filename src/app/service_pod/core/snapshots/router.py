import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Form, Response, UploadFile, status

from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.service_pod.core.access.service import PodAccessDep
from src.app.service_pod.core.snapshots import service
from src.app.service_pod.core.snapshots.contract import Basis, Collection, Provenance
from src.app.service_pod.core.snapshots.exceptions import SnapshotTooLargeError
from src.app.service_pod.core.snapshots.schemas import (
    QuickBooksSnapshotRequest,
    SnapshotImportResult,
    SnapshotRows,
    SnapshotSummary,
)

router = APIRouter(prefix="/snapshots", tags=["service pod: snapshots"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 413, 422)
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
    session: SessionDep, access: PodAccessDep, entity_id: uuid.UUID | None = None
) -> list[SnapshotSummary]:
    return await service.list_snapshots(session, access, entity_id)


@router.get("/{snapshot_id}", response_model=SnapshotSummary, responses=_ERRORS)
async def get_snapshot(
    snapshot_id: uuid.UUID, session: SessionDep, access: PodAccessDep
) -> SnapshotSummary:
    return await service.get_snapshot(session, access, snapshot_id)


@router.get("/{snapshot_id}/rows", response_model=SnapshotRows, responses=_ERRORS)
async def get_rows(
    snapshot_id: uuid.UUID, collection: Collection, session: SessionDep, access: PodAccessDep
) -> SnapshotRows:
    """One collection's rows, if your roles include it."""
    return await service.get_rows(session, access, snapshot_id, collection)
