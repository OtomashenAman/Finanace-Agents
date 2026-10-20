import json
import urllib.parse
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Form, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from src.app.agent_catalog.runs.exceptions import DocumentTooLargeError
from src.app.auth.dependencies import AdminUser, CurrentUser
from src.app.common.context import RequestContextDep
from src.app.common.schemas import ErrorResponse
from src.app.core.config import get_settings
from src.app.core.db import SessionDep
from src.app.data_sources import service
from src.app.data_sources.exceptions import UploadRejectedError
from src.app.data_sources.records import RecordType
from src.app.data_sources.schemas import (
    AdminDataSourceOut,
    AuthorizeResponse,
    DataSourceOut,
    QuickBooksApp,
    QuickBooksAppUpdate,
    RecordOut,
    RecordTypeInfo,
    RedirectUri,
    SourceUpdate,
    UploadPreview,
    UploadResult,
)

router = APIRouter(prefix="/data-sources", tags=["data sources"])
admin_router = APIRouter(prefix="/admin", tags=["data sources (admin)"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (403, 404, 409, 413, 422, 502)
}
RETURN_PATH = "/data-sources"


async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise DocumentTooLargeError(f"Files can be at most {limit // (1024 * 1024)} MB.")
    return data


def _parse_mapping(raw: str | None) -> dict[str, str | None] | None:
    if raw is None:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UploadRejectedError("The column mapping isn't valid JSON.") from exc
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in mapping.items()
    ):
        raise UploadRejectedError("The column mapping must map field names to column names.")
    return mapping


# --- the user's own sources (static paths first: "/{source_id}" would shadow them) -----


@router.get("", response_model=list[DataSourceOut])
async def list_sources(session: SessionDep, user: CurrentUser) -> list[DataSourceOut]:
    """Your connected companies and uploads."""
    return await service.list_sources(session, user)


@router.get("/record-types", response_model=list[RecordTypeInfo])
async def record_types(_: CurrentUser) -> list[RecordTypeInfo]:
    """What can be uploaded, and the fields each type has."""
    return service.record_types()


@router.get("/quickbooks/redirect-uri", response_model=RedirectUri)
async def quickbooks_redirect_uri(_: CurrentUser) -> RedirectUri:
    """The Redirect URI to register in your Intuit app, exactly as returned."""
    return service.redirect_uri()


@router.post("/quickbooks", response_model=AuthorizeResponse, responses=_ERRORS)
async def connect_quickbooks(
    body: QuickBooksApp, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> AuthorizeResponse:
    """Connect a company with your own Intuit app; returns the Intuit sign-in URL."""
    return await service.connect_quickbooks(session, user, body, ctx)


@router.get("/quickbooks/callback", include_in_schema=False)
async def quickbooks_callback(
    session: SessionDep,
    ctx: RequestContextDep,
    state: str | None = None,
    code: str | None = None,
    realmId: str | None = None,  # Intuit's parameter name
    error: str | None = None,
) -> RedirectResponse:
    """Intuit redirects the browser here. No session needed: the signed, single-use state
    identifies the user and source. Always sends the browser back to the Data Sources page."""
    source_id, message = await service.complete_authorization(
        session, state=state, code=code, realm_id=realmId, error=error, ctx=ctx
    )
    params = {"quickbooks": "error" if message else "connected"}
    if source_id:
        params["source"] = str(source_id)
    if message:
        params["message"] = message
    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(
        f"{base}{RETURN_PATH}?{urllib.parse.urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/uploads/preview", response_model=UploadPreview, responses=_ERRORS)
async def preview_upload(
    file: UploadFile,
    record_type: Annotated[RecordType, Form()],
    _: CurrentUser,
    mapping: Annotated[str | None, Form(description="JSON {field: column}")] = None,
) -> UploadPreview:
    """Read the file and check it against a column mapping (suggested when omitted)."""
    data = await _read_upload(file)
    return service.preview_upload(
        data, file.filename or "upload", record_type, _parse_mapping(mapping)
    )


@router.post(
    "/uploads",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def import_upload(
    file: UploadFile,
    record_type: Annotated[RecordType, Form()],
    mapping: Annotated[str, Form(description="JSON {field: column}")],
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
    name: Annotated[str | None, Form(max_length=200)] = None,
    skip_invalid: Annotated[bool, Form()] = False,
) -> UploadResult:
    """Import as a new data source. Only the records (and the file's SHA-256) are kept."""
    data = await _read_upload(file)
    return await service.import_upload(
        session,
        user,
        data=data,
        filename=file.filename or "upload",
        record_type=record_type,
        mapping=_parse_mapping(mapping) or {},
        name=name,
        skip_invalid=skip_invalid,
        ctx=ctx,
    )


@router.get("/{source_id}", response_model=DataSourceOut, responses=_ERRORS)
async def get_source(source_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> DataSourceOut:
    return await service.get_source(session, user, source_id)


@router.patch("/{source_id}", response_model=DataSourceOut, responses=_ERRORS)
async def rename_source(
    source_id: uuid.UUID, body: SourceUpdate, session: SessionDep, user: CurrentUser
) -> DataSourceOut:
    return await service.rename_source(session, user, source_id, body.name)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_ERRORS,
)
async def delete_source(
    source_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> Response:
    """Disconnect (revokes QuickBooks access) or remove an upload. Runs keep their snapshot."""
    await service.delete_source(session, user, source_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/authorize", response_model=AuthorizeResponse, responses=_ERRORS)
async def authorize_source(
    source_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> AuthorizeResponse:
    """Re-authorize a QuickBooks connection (e.g. after access expired)."""
    return await service.authorize_source(session, user, source_id, ctx)


@router.put("/{source_id}/app", response_model=DataSourceOut, responses=_ERRORS)
async def update_app(
    source_id: uuid.UUID,
    body: QuickBooksAppUpdate,
    session: SessionDep,
    user: CurrentUser,
    ctx: RequestContextDep,
) -> DataSourceOut:
    """Change the connection's Intuit app (Client ID/Secret, environment)."""
    return await service.update_app(session, user, source_id, body, ctx)


@router.post("/{source_id}/sync", response_model=DataSourceOut, responses=_ERRORS)
async def sync_source(
    source_id: uuid.UUID, session: SessionDep, user: CurrentUser, ctx: RequestContextDep
) -> DataSourceOut:
    """Pull the latest vendors, bills, purchase orders and accounts from QuickBooks."""
    return await service.sync_source(session, user, source_id, ctx)


@router.get("/{source_id}/records", response_model=list[RecordOut], responses=_ERRORS)
async def list_records(
    source_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    record_type: Annotated[RecordType, Query(alias="type")],
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[RecordOut]:
    return await service.list_records(session, user, source_id, record_type, search, limit)


# --- Finance Admin ----------------------------------------------------------------------


@admin_router.get("/data-sources", response_model=list[AdminDataSourceOut])
async def list_all_sources(session: SessionDep, _: AdminUser) -> list[AdminDataSourceOut]:
    """Every user's sources, status only (no credentials, no records)."""
    return await service.list_all_sources(session)
