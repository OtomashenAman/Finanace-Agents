"""Removing a user's Service POD data (admin): their data sources and what was made from them,
the snapshots they imported (with what was built on them) and the cases they opened. The user
is kept, deactivated and signed out: other people's records (approvals, audit) still name
them. The 12 agents' runs are not touched."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.audit.service import record_event
from src.app.auth.models import User
from src.app.auth.service import revoke_user_tokens
from src.app.common.context import RequestContext
from src.app.core.errors import AppError
from src.app.data_sources import service as data_sources_service
from src.app.data_sources.models import DataSource
from src.app.service_pod.core.access.service import PodAccess
from src.app.service_pod.core.cases.models import PodCase
from src.app.service_pod.core.snapshots import purge
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.snapshots.schemas import UserDataPreview


class UserDataError(AppError):
    status_code = 409
    code = "user_data_refused"


async def _scope(
    session: AsyncSession, user: User
) -> tuple[list[DataSource], list[uuid.UUID], list[uuid.UUID]]:
    sources = list(await session.scalars(select(DataSource).where(DataSource.owner_id == user.id)))
    roots = list(
        await session.scalars(select(PodSnapshot.id).where(PodSnapshot.imported_by == user.id))
    )
    for source in sources:
        roots += await purge.source_snapshot_ids(session, source.id)
    snapshot_ids = await purge._with_descendants(session, roots)
    case_ids = list(
        await session.scalars(
            select(PodCase.id).where(
                (PodCase.owner_id == user.id)
                | PodCase.snapshot_id.in_(snapshot_ids or [uuid.uuid4()])
            )
        )
    )
    return sources, snapshot_ids, case_ids


async def _user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise UserDataError("User not found.")
    return user


async def preview(session: AsyncSession, user_id: uuid.UUID) -> UserDataPreview:
    user = await _user(session, user_id)
    sources, snapshot_ids, case_ids = await _scope(session, user)
    return UserDataPreview(
        user_name=user.full_name,
        data_sources=[s.name for s in sources],
        **(await purge.preview_cases(session, case_ids, snapshot_ids)).model_dump(),
    )


async def remove(
    session: AsyncSession,
    access: PodAccess,
    user_id: uuid.UUID,
    reason: str,
    confirm: str,
    ctx: RequestContext,
) -> UserDataPreview:
    user = await _user(session, user_id)
    if user.id == access.user.id:
        raise UserDataError("You can't remove your own data: another admin has to.")
    if confirm.strip().casefold() != user.email.strip().casefold():
        raise purge.PurgeConfirmationError("Type the user's email exactly to confirm.")
    gone = await preview(session, user_id)
    sources, snapshot_ids, case_ids = await _scope(session, user)
    record_event(
        session,
        "pod.user_data_removed",
        ctx,
        actor_id=access.user.id,
        user_id=str(user.id),
        reason=reason,
        data_sources=gone.data_sources,
        cases=[c.reference for c in gone.cases],
        snapshots=[str(s.id) for s in gone.snapshots],
        evidence=gone.evidence,
        summary=(
            f"Removed {user.full_name}'s Service POD data: {len(gone.data_sources)} data "
            f"source(s), {len(gone.snapshots)} snapshot(s), {len(gone.cases)} case(s): {reason}"
        ),
    )
    await purge.purge_cases(session, case_ids)
    await purge.purge_snapshots(session, snapshot_ids)
    user.is_active = False
    await revoke_user_tokens(session, user.id)
    await session.commit()
    # Then each data source the usual way: QuickBooks access is revoked, records dropped
    for source_id in [s.id for s in sources]:
        await data_sources_service.delete_source(session, user, source_id, ctx)
    return gone
