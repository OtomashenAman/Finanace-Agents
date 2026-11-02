"""What the Finance POD's workflows share: the case's source data, its policy, earlier step
results, and the outbound mail an agent drafts (a person still approves and sends it)."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.governance.models import AgentPolicy
from src.app.service_pod.core.messaging import service as messaging
from src.app.service_pod.core.messaging.models import Audience, MessageStatus, PodMessage
from src.app.service_pod.core.messaging.schemas import MessageDraftIn
from src.app.service_pod.core.snapshots import service as snapshots
from src.app.service_pod.core.snapshots.contract import SnapshotDocument
from src.app.service_pod.core.snapshots.models import PodSnapshot
from src.app.service_pod.core.steps.spec import StepFailedError, StepStatus

if TYPE_CHECKING:
    from src.app.service_pod.core.cases.models import PodCase
    from src.app.service_pod.core.cases.service import Ctx

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


async def snapshot_of(c: Ctx) -> PodSnapshot:
    snapshot = await c.session.get(PodSnapshot, c.case.snapshot_id)
    assert snapshot is not None  # noqa: S101 - RESTRICT foreign key
    return snapshot


async def doc_of(c: Ctx) -> SnapshotDocument:
    return snapshots.document(await snapshot_of(c))


# --- policies -----------------------------------------------------------------------------


async def policy_values[P: BaseModel](
    session: AsyncSession, key: str, schema: type[P]
) -> tuple[str, P]:
    """(version label, values) in force for a workflow: the newest saved version (Admin
    Settings, versioned like the agents' thresholds), else the code defaults (v1)."""
    latest = await session.scalar(
        select(AgentPolicy)
        .where(AgentPolicy.agent_key == key)
        .order_by(AgentPolicy.version.desc())
        .limit(1)
    )
    if latest is None:
        return f"{key}/v1", schema()
    return f"{key}/v{latest.version + 1}", schema.model_validate(latest.values)


def policy_of[P: BaseModel](case: PodCase, schema: type[P]) -> P:
    """The policy the case was opened with (recorded in its state, so it's approved too)."""
    return schema.model_validate(case.state.get("policy", {}).get("values", {}))


# --- earlier steps ------------------------------------------------------------------------


def result[M: BaseModel](c: Ctx, l5_code: str, model: type[M]) -> M | None:
    """The validated result of a done L5 step (None: not done, or not applicable)."""
    row = next((r for r in c.children.steps if r.l5_code == l5_code), None)
    if row is None or row.status != StepStatus.DONE or row.result is None:
        return None
    return model.model_validate(row.result)


def need[M: BaseModel](c: Ctx, l5_code: str, model: type[M]) -> M:
    found = result(c, l5_code, model)
    if found is None:
        raise StepFailedError(f"{l5_code} isn't done.")
    return found


def step_status(c: Ctx, l5_code: str) -> StepStatus:
    row = next((r for r in c.children.steps if r.l5_code == l5_code), None)
    return row.status if row else StepStatus.PENDING


# --- mail an agent drafts -----------------------------------------------------------------


async def draft_once(
    c: Ctx,
    *,
    purpose: str,
    audience: Audience,
    to_email: str,
    to_name: str | None,
    subject: str,
    body: str,
) -> PodMessage:
    """The case's draft (or sent message) of this purpose to this address, made once."""
    existing = await c.session.scalar(
        select(PodMessage).where(
            PodMessage.case_id == c.case.id,
            PodMessage.purpose == purpose,
            PodMessage.to_email == to_email,
            PodMessage.status != MessageStatus.SEND_FAILED,
        )
    )
    if existing is not None:
        return existing
    return await messaging.add_draft(
        c.session,
        c.case,
        MessageDraftIn(
            audience=audience,
            purpose=purpose,
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body=body,
        ),
        c.user.id,
    )


def is_sent(message: PodMessage) -> bool:
    return message.status == MessageStatus.SENT


def money_text(value: Decimal, currency: str) -> str:
    return f"{currency} {cents(value):,.2f}"


def iso(value: date | None) -> str:
    return value.isoformat() if value else "n/a"


def jsonable(value: Any) -> Any:
    from src.app.service_pod.common.canonical import plain

    return plain(value)
