"""Data sources: each user's own QuickBooks connections and uploads.

Secrets are encrypted at rest and never returned. Every query is scoped to the owner; other
users' sources behave as if they don't exist (admins get a status-only overview).
"""

import contextlib
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import PurePath
from typing import Any

import jwt
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.auth.security import create_purpose_token, decode_purpose_token
from src.app.common.clock import utcnow
from src.app.common.context import RequestContext
from src.app.common.text_extraction.base import ExtractionError
from src.app.core.config import get_settings
from src.app.core.llm.factory import get_llm_provider
from src.app.data_sources import crypto
from src.app.data_sources import uploads as upload_parser
from src.app.data_sources.access import to_record
from src.app.data_sources.exceptions import (
    AppCredentialsError,
    DataSourceNotFoundError,
    RecordNotFoundError,
    SourceNotSyncableError,
    SyncFailedError,
    UploadRejectedError,
)
from src.app.data_sources.models import (
    DataSource,
    FinanceRecord,
    HistoryStatus,
    IntegrationEnvironment,
    SourceKind,
    SourceStatus,
)
from src.app.data_sources.providers import quickbooks as qb
from src.app.data_sources.records import RECORD_LABELS, Record, RecordType
from src.app.data_sources.schemas import (
    AdminDataSourceOut,
    AuthorizeResponse,
    DataSourceOut,
    FieldSpec,
    QuickBooksApp,
    QuickBooksAppUpdate,
    RecordOut,
    RecordTypeInfo,
    RedirectUri,
    SourceOwner,
    UploadPreview,
    UploadResult,
)
from src.app.jobs import queue as jobs
from src.app.jobs.queue import JobContext

STATE_PURPOSE = "quickbooks_oauth"
STATE_TTL = timedelta(minutes=15)
PENDING_NAME = "QuickBooks (authorization pending)"


# --- sources ----------------------------------------------------------------------------


async def _owned(
    session: AsyncSession, user: User, source_id: uuid.UUID, *, lock: bool = False
) -> DataSource:
    query = select(DataSource).where(DataSource.id == source_id, DataSource.owner_id == user.id)
    source = await session.scalar(query.with_for_update() if lock else query)
    if source is None:
        raise DataSourceNotFoundError
    return source


async def list_sources(session: AsyncSession, user: User) -> list[DataSourceOut]:
    sources = await session.scalars(
        select(DataSource).where(DataSource.owner_id == user.id).order_by(DataSource.created_at)
    )
    return [DataSourceOut.model_validate(s) for s in sources]


async def get_source(session: AsyncSession, user: User, source_id: uuid.UUID) -> DataSourceOut:
    return DataSourceOut.model_validate(await _owned(session, user, source_id))


async def list_all_sources(session: AsyncSession) -> list[AdminDataSourceOut]:
    rows = await session.execute(
        select(DataSource, User)
        .join(User, User.id == DataSource.owner_id)
        .order_by(User.full_name, DataSource.created_at)
    )
    return [
        AdminDataSourceOut(
            **DataSourceOut.model_validate(source).model_dump(),
            owner=SourceOwner(id=owner.id, full_name=owner.full_name, email=owner.email),
        )
        for source, owner in rows
    ]


NEEDS_ATTENTION = (SourceStatus.NEEDS_REAUTH, SourceStatus.ERROR, SourceStatus.PENDING_AUTH)


async def attention_sources(
    session: AsyncSession, owner_id: uuid.UUID | None
) -> list[tuple[DataSource, User]]:
    """Connections that need their owner (one owner, or everyone's for an admin overview)."""
    query = (
        select(DataSource, User)
        .join(User, User.id == DataSource.owner_id)
        .where(DataSource.status.in_(NEEDS_ATTENTION))
        .order_by(DataSource.updated_at)
    )
    if owner_id is not None:
        query = query.where(DataSource.owner_id == owner_id)
    return [(source, owner) for source, owner in await session.execute(query)]


async def health_summary(session: AsyncSession) -> str:
    """One line for the admin overview, e.g. "3 connected · 1 needs re-authorization"."""
    result = await session.execute(
        select(DataSource.status, func.count())
        .where(DataSource.kind == SourceKind.QUICKBOOKS)
        .group_by(DataSource.status)
    )
    rows: dict[SourceStatus, int] = dict(result.all())
    if not rows:
        return "Not configured"
    parts = [f"{rows.get(SourceStatus.CONNECTED, 0)} connected"]
    if attention := rows.get(SourceStatus.NEEDS_REAUTH, 0) + rows.get(SourceStatus.ERROR, 0):
        parts.append(f"{attention} need attention")
    return " · ".join(parts)


async def rename_source(
    session: AsyncSession, user: User, source_id: uuid.UUID, name: str
) -> DataSourceOut:
    source = await _owned(session, user, source_id, lock=True)
    source.name = name.strip()
    await session.commit()
    return DataSourceOut.model_validate(source)


async def delete_source(
    session: AsyncSession, user: User, source_id: uuid.UUID, ctx: RequestContext
) -> None:
    """Disconnect (revoking QuickBooks access) and drop its records. Run snapshots stay."""
    source = await _owned(session, user, source_id, lock=True)
    if source.kind == SourceKind.QUICKBOOKS and source.credentials_enc:
        try:
            tokens = qb.Tokens.from_json(crypto.decrypt_json(source.credentials_enc))
            await qb.revoke(_app_for(source), tokens.refresh_token)
        except (AppCredentialsError, ValueError, KeyError):
            pass  # nothing usable to revoke; deleting locally still ends our access
    record_event(
        session,
        "data_source.deleted",
        ctx,
        actor_id=user.id,
        source_id=str(source.id),
        kind=source.kind.value,
        name=source.name,
    )
    await session.delete(source)
    await session.commit()


async def _replace_records(
    session: AsyncSession, source: DataSource, records: dict[RecordType, list[Record]]
) -> None:
    """Replace the source's records of the given types (other types are kept)."""
    await session.execute(
        delete(FinanceRecord).where(
            FinanceRecord.source_id == source.id, FinanceRecord.record_type.in_(list(records))
        )
    )
    for record_type, items in records.items():
        session.add_all(
            FinanceRecord(
                source_id=source.id,
                record_type=record_type,
                external_id=r.external_id,
                reference=r.reference[:200],
                counterparty=r.counterparty[:200] if r.counterparty else None,
                amount=r.amount,
                txn_date=r.txn_date,
                data=r.model_dump(mode="json"),
            )
            for r in items
        )
    source.record_counts = {
        **source.record_counts,
        **{t.value: len(items) for t, items in records.items()},
    }


# --- QuickBooks OAuth -------------------------------------------------------------------


def _app_for(source: DataSource) -> qb.AppCredentials:
    """The source owner's own Intuit app."""
    if not source.client_id or not source.client_secret_enc or not source.environment:
        raise AppCredentialsError
    try:
        secret = crypto.decrypt(source.client_secret_enc)
    except ValueError as exc:
        raise AppCredentialsError(
            "Your QuickBooks Client Secret can't be read. Enter it again."
        ) from exc
    return qb.AppCredentials(source.client_id, secret, source.environment)


def _set_app(
    source: DataSource, client_id: str, secret: str | None, environment: IntegrationEnvironment
) -> bool:
    """Store the Intuit app; returns whether it changed (old tokens are then unusable)."""
    changed = source.client_id != client_id.strip() or source.environment != environment
    source.client_id = client_id.strip()
    source.environment = environment
    if secret is not None:
        source.client_secret_enc = crypto.encrypt(secret.strip())
        changed = True
    return changed


def redirect_uri() -> RedirectUri:
    return RedirectUri(redirect_uri=qb.redirect_uri())


async def _authorization(
    session: AsyncSession, user: User, source: DataSource, ctx: RequestContext
) -> AuthorizeResponse:
    app = _app_for(source)
    # Single use: the callback must present this exact value, then it is cleared
    source.oauth_nonce = secrets.token_urlsafe(24)
    state = create_purpose_token(
        STATE_PURPOSE,
        {"sub": str(user.id), "sid": str(source.id), "nonce": source.oauth_nonce},
        STATE_TTL,
    )
    record_event(
        session,
        "data_source.authorization_started",
        ctx,
        actor_id=user.id,
        source_id=str(source.id),
    )
    await session.commit()
    return AuthorizeResponse(
        source=DataSourceOut.model_validate(source), url=qb.authorization_url(app, state)
    )


async def connect_quickbooks(
    session: AsyncSession, user: User, body: QuickBooksApp, ctx: RequestContext
) -> AuthorizeResponse:
    """Start connecting a company with the user's own Intuit app.

    An unfinished connection (never authorized) is reused, so retrying or double-clicking
    doesn't pile up empty sources.
    """
    source = await session.scalar(
        select(DataSource)
        .where(
            DataSource.owner_id == user.id,
            DataSource.kind == SourceKind.QUICKBOOKS,
            DataSource.status == SourceStatus.PENDING_AUTH,
            DataSource.external_id.is_(None),
        )
        .order_by(DataSource.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if source is None:
        source = DataSource(
            owner_id=user.id,
            kind=SourceKind.QUICKBOOKS,
            name=PENDING_NAME,
            status=SourceStatus.PENDING_AUTH,
        )
        session.add(source)
    _set_app(source, body.client_id, body.client_secret, body.environment)
    source.last_error = None
    await session.flush()
    return await _authorization(session, user, source, ctx)


async def authorize_source(
    session: AsyncSession, user: User, source_id: uuid.UUID, ctx: RequestContext
) -> AuthorizeResponse:
    """Re-authorize one of the user's own connections (same Intuit app)."""
    source = await _owned(session, user, source_id, lock=True)
    if source.kind != SourceKind.QUICKBOOKS:
        raise DataSourceNotFoundError
    return await _authorization(session, user, source, ctx)


async def update_app(
    session: AsyncSession,
    user: User,
    source_id: uuid.UUID,
    body: QuickBooksAppUpdate,
    ctx: RequestContext,
) -> DataSourceOut:
    """Change the Intuit app of a connection. A different app needs a new authorization."""
    source = await _owned(session, user, source_id, lock=True)
    if source.kind != SourceKind.QUICKBOOKS:
        raise DataSourceNotFoundError
    if _set_app(source, body.client_id, body.client_secret, body.environment):
        source.credentials_enc = None  # tokens belong to the previous app
        source.status = (
            SourceStatus.NEEDS_REAUTH if source.external_id else SourceStatus.PENDING_AUTH
        )
        source.last_error = "App credentials changed: re-authorize to continue."
        record_event(
            session,
            "data_source.app_updated",
            ctx,
            actor_id=user.id,
            source_id=str(source.id),
            environment=body.environment.value,
            secret_changed=body.client_secret is not None,
        )
        await session.commit()
    return DataSourceOut.model_validate(source)


async def complete_authorization(
    session: AsyncSession,
    *,
    state: str | None,
    code: str | None,
    realm_id: str | None,
    error: str | None,
    ctx: RequestContext,
) -> tuple[uuid.UUID | None, str | None]:
    """Finish Intuit's redirect. Returns (source id, error message for the user)."""
    try:
        claims = decode_purpose_token(state or "", STATE_PURPOSE)
        owner_id, source_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None, "This authorization link expired or is invalid. Connect again."

    source = await session.scalar(
        select(DataSource)
        .where(DataSource.id == source_id, DataSource.owner_id == owner_id)
        .with_for_update()
    )
    if source is None or not source.oauth_nonce or source.oauth_nonce != claims.get("nonce"):
        return None, "This authorization link was already used or replaced. Connect again."
    source.oauth_nonce = None

    async def fail(message: str) -> tuple[uuid.UUID | None, str | None]:
        source.last_error = message[:500]
        record_event(
            session,
            "data_source.authorization_failed",
            ctx,
            actor_id=owner_id,
            source_id=str(source.id),
            reason=message[:200],
        )
        await session.commit()
        return source.id, message

    if error:
        return await fail("QuickBooks authorization was cancelled.")
    if not code or not realm_id:
        return await fail("QuickBooks didn't return a company. Connect again.")
    if source.external_id and source.external_id != realm_id:
        return await fail(
            "You picked a different company. Re-authorize the same company, or connect the "
            "other one as a new data source."
        )
    duplicate = await session.scalar(
        select(DataSource.id).where(
            DataSource.owner_id == owner_id,
            DataSource.kind == SourceKind.QUICKBOOKS,
            DataSource.external_id == realm_id,
            DataSource.id != source.id,
        )
    )
    if duplicate is not None:
        return await fail("This QuickBooks company is already connected as another data source.")

    try:
        app = _app_for(source)
        tokens = await qb.exchange_code(app, code)
    except (AppCredentialsError, qb.QuickBooksError) as exc:
        return await fail(str(exc))

    source.credentials_enc = crypto.encrypt_json(tokens.to_json())
    source.external_id = realm_id
    source.status = SourceStatus.CONNECTED
    source.last_error = None
    record_event(
        session,
        "data_source.authorized",
        ctx,
        actor_id=owner_id,
        source_id=str(source.id),
        realm_id=realm_id,
    )
    await session.commit()

    # First sync right away so the user lands on a usable source; a failure is shown on it
    with contextlib.suppress(SourceNotSyncableError, SyncFailedError):
        await _sync(session, source, app, ctx, owner_id)
    return source.id, None


async def _access_tokens(
    session: AsyncSession, source: DataSource, app: qb.AppCredentials
) -> qb.Tokens:
    if not source.credentials_enc:
        raise qb.ReauthorizationRequired("Authorize this QuickBooks connection first.")
    try:
        tokens = qb.Tokens.from_json(crypto.decrypt_json(source.credentials_enc))
    except (ValueError, KeyError) as exc:
        raise qb.ReauthorizationRequired("Stored QuickBooks access can't be read.") from exc
    if tokens.expired:
        tokens = await qb.refresh(app, tokens.refresh_token)
        # Intuit rotates refresh tokens: persist the new one before anything else can fail
        source.credentials_enc = crypto.encrypt_json(tokens.to_json())
        await session.flush()
    return tokens


async def _sync(
    session: AsyncSession,
    source: DataSource,
    app: qb.AppCredentials,
    ctx: RequestContext,
    actor_id: uuid.UUID,
) -> None:
    assert source.external_id is not None  # noqa: S101 - set when authorized
    try:
        tokens = await _access_tokens(session, source, app)
        async with qb.client() as http:
            api = qb.Api(http, app, source.external_id, tokens.access_token)
            snapshot = await qb.fetch_all(api, source.external_id)
    except qb.ReauthorizationRequired as exc:
        source.status = SourceStatus.NEEDS_REAUTH
        source.last_error = str(exc)
        await session.commit()
        raise SourceNotSyncableError(f"{exc} Re-authorize to continue.") from exc
    except qb.QuickBooksError as exc:
        source.status = SourceStatus.ERROR
        source.last_error = str(exc)
        await session.commit()
        raise SyncFailedError(str(exc)) from exc

    await _replace_records(session, source, snapshot.records)
    source.last_synced_at = utcnow()
    source.name = snapshot.company_name or f"QuickBooks company {source.external_id}"
    source.status = SourceStatus.CONNECTED
    source.last_error = (
        f"{snapshot.skipped} QuickBooks record(s) couldn't be read and were skipped."
        if snapshot.skipped
        else None
    )
    record_event(
        session,
        "data_source.synced",
        ctx,
        actor_id=actor_id,
        source_id=str(source.id),
        counts=source.record_counts,
        skipped=snapshot.skipped,
    )
    # Month-end history takes dozens of report calls: fetched in the background
    source.history_status = HistoryStatus.PENDING
    job = await jobs.enqueue(
        session,
        HISTORY_JOB,
        {"source_id": str(source.id)},
        dedupe_key=f"{HISTORY_JOB}:{source.id}:{source.last_synced_at.isoformat()}",
    )
    await session.commit()
    await jobs.dispatch(session, job, get_llm_provider())


HISTORY_JOB = "data_source.history"


@jobs.handler(HISTORY_JOB)
async def sync_history(session: AsyncSession, payload: dict[str, Any], ctx: JobContext) -> None:
    """Month-end trial balances, AR/AP aging totals and the books closing date."""
    source = await session.get(DataSource, uuid.UUID(payload["source_id"]), with_for_update=True)
    if source is None or source.kind != SourceKind.QUICKBOOKS:
        return  # deleted meanwhile, or not QuickBooks
    try:
        app = _app_for(source)
        tokens = await _access_tokens(session, source, app)
        # A refreshed (rotated) token must survive a failure below: keep it now
        await session.commit()
        assert source.external_id is not None  # noqa: S101 - set when authorized
        async with qb.client() as http:
            api = qb.Api(http, app, source.external_id, tokens.access_token)
            history = await qb.fetch_history(api, utcnow().date())
    except (qb.QuickBooksError, AppCredentialsError) as exc:
        if isinstance(exc, qb.ReauthorizationRequired):
            source.status = SourceStatus.NEEDS_REAUTH
        elif not ctx.final_attempt:
            raise jobs.RetryLater(str(exc)) from exc
        source.history_status = HistoryStatus.ERROR
        source.history_error = f"Month-end history couldn't be fetched: {exc}"[:500]
        return
    await _replace_records(session, source, history.records)
    source.books_closed_through = (
        date.fromisoformat(history.books_closed_through) if history.books_closed_through else None
    )
    source.history_status = HistoryStatus.READY
    source.history_synced_at = utcnow()
    source.history_error = None


async def sync_source(
    session: AsyncSession, user: User, source_id: uuid.UUID, ctx: RequestContext
) -> DataSourceOut:
    source = await _owned(session, user, source_id, lock=True)
    if source.kind != SourceKind.QUICKBOOKS:
        raise SourceNotSyncableError("Uploads don't sync: upload a new file instead.")
    if source.status in (SourceStatus.PENDING_AUTH, SourceStatus.NEEDS_REAUTH):
        raise SourceNotSyncableError("Re-authorize this QuickBooks connection first.")
    await _sync(session, source, _app_for(source), ctx, user.id)
    return DataSourceOut.model_validate(source)


# --- uploads ----------------------------------------------------------------------------


def record_types() -> list[RecordTypeInfo]:
    return [
        RecordTypeInfo(
            type=t,
            label=RECORD_LABELS[t],
            fields=[FieldSpec(name=n, required=r) for n, r in upload_parser.fields_for(t).items()],
        )
        for t in RecordType
    ]


def _parse(
    data: bytes,
    filename: str,
    record_type: RecordType,
    mapping: dict[str, str | None] | None,
) -> tuple[upload_parser.Table, dict[str, str | None], upload_parser.ImportResult]:
    try:
        table = upload_parser.read_table(data, filename, get_settings().upload_max_rows)
    except ExtractionError as exc:
        raise UploadRejectedError(str(exc)) from exc
    fields = upload_parser.fields_for(record_type)
    if mapping is None:
        mapping = upload_parser.suggest_mapping(record_type, table.headers)
    else:
        unknown = [f for f in mapping if f not in fields]
        if unknown:
            raise UploadRejectedError(f"Unknown field(s): {', '.join(unknown)}.")
        missing_headers = [h for h in mapping.values() if h and h not in table.headers]
        if missing_headers:
            raise UploadRejectedError(f"Column(s) not in the file: {', '.join(missing_headers)}.")
        mapping = {f: mapping.get(f) for f in fields}
    return table, mapping, upload_parser.build_records(record_type, table, mapping)


def preview_upload(
    data: bytes, filename: str, record_type: RecordType, mapping: dict[str, str | None] | None
) -> UploadPreview:
    table, mapping, result = _parse(data, filename, record_type, mapping)
    unmapped = [
        f
        for f, required in upload_parser.fields_for(record_type).items()
        if required and not mapping.get(f)
    ]
    errors = [f"Map a column to the required field '{f}'." for f in unmapped] + result.errors
    return UploadPreview(
        record_type=record_type,
        headers=table.headers,
        mapping=mapping,
        sample_rows=table.rows[: upload_parser.PREVIEW_ROWS],
        row_count=len(table.rows),
        valid_count=0 if unmapped else len(result.records),
        error_count=len(table.rows) if unmapped else result.error_count,
        errors=errors[: upload_parser.MAX_REPORTED_ERRORS],
    )


async def import_upload(
    session: AsyncSession,
    user: User,
    *,
    data: bytes,
    filename: str,
    record_type: RecordType,
    mapping: dict[str, str | None],
    name: str | None,
    skip_invalid: bool,
    ctx: RequestContext,
) -> UploadResult:
    _, mapping, result = _parse(data, filename, record_type, mapping)
    unmapped = [
        f
        for f, required in upload_parser.fields_for(record_type).items()
        if required and not mapping.get(f)
    ]
    if unmapped:
        raise UploadRejectedError(f"Map a column to: {', '.join(unmapped)}.")
    if not result.records:
        first = result.errors[0] if result.errors else "no rows"
        raise UploadRejectedError(f"No valid rows to import. {first}")
    if result.error_count and not skip_invalid:
        raise UploadRejectedError(
            f"{result.error_count} row(s) have problems. Fix the file, or import only the "
            f"{len(result.records)} valid row(s). First: {result.errors[0]}"
        )

    sha256 = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(DataSource.name).where(
            DataSource.owner_id == user.id,
            DataSource.sha256 == sha256,
            DataSource.kind == SourceKind.UPLOAD,
        )
    )
    if existing is not None:
        raise UploadRejectedError(f"This file is already uploaded as '{existing}'.")

    source = DataSource(
        owner_id=user.id,
        kind=SourceKind.UPLOAD,
        name=(name or "").strip()[:200] or PurePath(filename).stem[:200] or "Upload",
        status=SourceStatus.READY,
        filename=PurePath(filename).name[:255],
        sha256=sha256,
    )
    session.add(source)
    await session.flush()
    await _replace_records(session, source, {record_type: result.records})
    source.last_synced_at = utcnow()
    record_event(
        session,
        "data_source.uploaded",
        ctx,
        actor_id=user.id,
        source_id=str(source.id),
        filename=source.filename,
        sha256=sha256,
        record_type=record_type.value,
        imported=len(result.records),
        skipped=result.error_count,
    )
    await session.commit()
    return UploadResult(
        source=DataSourceOut.model_validate(source),
        imported=len(result.records),
        skipped=result.error_count,
    )


# --- records ----------------------------------------------------------------------------


def _record_out(row: FinanceRecord) -> RecordOut:
    return RecordOut(
        external_id=row.external_id,
        record_type=row.record_type,
        reference=row.reference,
        counterparty=row.counterparty,
        amount=row.amount,
        txn_date=row.txn_date,
        data=row.data,
    )


async def list_records(
    session: AsyncSession,
    user: User,
    source_id: uuid.UUID,
    record_type: RecordType,
    search: str | None,
    limit: int,
) -> list[RecordOut]:
    source = await _owned(session, user, source_id)
    query = select(FinanceRecord).where(
        FinanceRecord.source_id == source.id, FinanceRecord.record_type == record_type
    )
    if search and (term := search.strip()):
        pattern = f"%{term}%"
        query = query.where(
            FinanceRecord.reference.ilike(pattern) | FinanceRecord.counterparty.ilike(pattern)
        )
    rows = await session.scalars(
        query.order_by(FinanceRecord.txn_date.desc().nulls_last(), FinanceRecord.reference).limit(
            limit
        )
    )
    return [_record_out(r) for r in rows]


async def owned_source(session: AsyncSession, user: User, source_id: uuid.UUID) -> DataSource:
    """One of the user's own sources (for prefilling a run from its data)."""
    return await _owned(session, user, source_id)


async def owned_record(
    session: AsyncSession,
    user: User,
    source_id: uuid.UUID,
    record_type: RecordType,
    external_id: str,
) -> tuple[DataSource, Record]:
    """A record from one of the user's own sources (for prefilling a run)."""
    source = await _owned(session, user, source_id)
    row = await session.scalar(
        select(FinanceRecord).where(
            FinanceRecord.source_id == source.id,
            FinanceRecord.record_type == record_type,
            FinanceRecord.external_id == external_id,
        )
    )
    if row is None:
        raise RecordNotFoundError
    return source, to_record(row)


# --- write-back (after approval) --------------------------------------------------------


async def stamp_bill(
    session: AsyncSession, source_id: uuid.UUID, bill_id: str, marker: str, line: str
) -> dict[str, Any]:
    """Append `line` to a QuickBooks bill's private note unless `marker` is already there.

    Only the note changes (sparse update). Returns the receipt to keep on the run.
    """
    source = await session.get(DataSource, source_id, with_for_update=True)
    if source is None or source.kind != SourceKind.QUICKBOOKS or not source.external_id:
        raise SourceNotSyncableError("The QuickBooks connection is gone.")
    app = _app_for(source)
    try:
        tokens = await _access_tokens(session, source, app)
        async with qb.client() as http:
            api = qb.Api(http, app, source.external_id, tokens.access_token)
            bill = await api.get_bill(bill_id)
            if not bill:
                raise qb.QuickBooksError(f"Bill {bill_id} no longer exists in QuickBooks.")
            note = str(bill.get("PrivateNote") or "")
            already = marker in note
            if not already:
                note = f"{note}\n{line}".strip()[:4000]
                bill = await api.set_bill_note(bill, note)
    except qb.ReauthorizationRequired as exc:
        source.status = SourceStatus.NEEDS_REAUTH
        source.last_error = str(exc)
        await session.commit()
        raise
    return {
        "system": "quickbooks",
        "company": source.external_id,
        "bill_id": bill_id,
        "sync_token": str(bill.get("SyncToken", "")),
        "note_line": line,
        "already_present": already,
        "updated_at": (bill.get("MetaData") or {}).get("LastUpdatedTime"),
    }


@dataclass(frozen=True)
class BillTarget:
    """Where an approved invoice becomes a QuickBooks bill: the user's connection, the
    vendor matched by name and the expense account they chose (all from the last sync)."""

    source_id: uuid.UUID
    company: str
    vendor_id: str
    vendor_name: str
    account_id: str
    account_name: str


async def bill_target(
    session: AsyncSession, user: User, source_id: uuid.UUID, supplier: str, account_id: str
) -> BillTarget:
    source = await _owned(session, user, source_id)
    if source.kind != SourceKind.QUICKBOOKS or source.status != SourceStatus.CONNECTED:
        raise SourceNotSyncableError("Pick one of your connected QuickBooks companies.")

    def record(record_type: RecordType) -> Any:
        return select(FinanceRecord).where(
            FinanceRecord.source_id == source.id, FinanceRecord.record_type == record_type
        )

    vendor = await session.scalar(
        record(RecordType.VENDOR).where(func.lower(FinanceRecord.reference) == supplier.lower())
    )
    if vendor is None:
        raise SourceNotSyncableError(
            f"No vendor named “{supplier}” in this QuickBooks company. Add it in QuickBooks "
            "(or fix the supplier name on the run), then sync."
        )
    account = await session.scalar(
        record(RecordType.ACCOUNT).where(FinanceRecord.external_id == account_id)
    )
    if account is None:
        raise RecordNotFoundError
    return BillTarget(
        source.id,
        source.name,
        vendor.external_id,
        vendor.reference,
        account.external_id,
        " ".join(filter(None, [account.data.get("number"), account.data.get("name")])),
    )


async def create_bill(
    session: AsyncSession,
    target: BillTarget,
    *,
    doc_number: str,
    amount: Decimal,
    note: str,
) -> dict[str, Any]:
    """Create the bill unless the vendor already has one with this number (e.g. a retry
    after a timeout, or entered by hand): then that bill is the receipt and nothing is
    written. Returns the receipt to keep on the run."""
    source = await session.get(DataSource, target.source_id, with_for_update=True)
    if source is None or source.kind != SourceKind.QUICKBOOKS or not source.external_id:
        raise SourceNotSyncableError("The QuickBooks connection is gone.")
    app = _app_for(source)
    try:
        tokens = await _access_tokens(session, source, app)
        async with qb.client() as http:
            api = qb.Api(http, app, source.external_id, tokens.access_token)
            bill = await api.find_bill(target.vendor_id, doc_number)
            already = bill is not None
            if bill is None:
                bill = await api.create_bill(
                    vendor_id=target.vendor_id,
                    account_id=target.account_id,
                    doc_number=doc_number,
                    amount=amount,
                    note=note,
                )
    except qb.ReauthorizationRequired as exc:
        source.status = SourceStatus.NEEDS_REAUTH
        source.last_error = str(exc)
        await session.commit()
        raise
    return {
        "system": "quickbooks",
        "company": source.external_id,
        "bill_id": str(bill.get("Id", "")),
        "doc_number": doc_number,
        "vendor": target.vendor_name,
        "account": target.account_name,
        "amount": str(bill.get("TotalAmt", amount)),
        "sync_token": str(bill.get("SyncToken", "")),
        "already_present": already,
        "updated_at": (bill.get("MetaData") or {}).get("LastUpdatedTime"),
    }
