"""Finance Admin governance: maker-checker setting, versioned thresholds, approval matrix.

Runs record what applied to them (policy version + values on analyze, approval tier on
submit), so a later change never rewrites history.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import BaseAgent
from src.app.agent_catalog.agents.fields import PolicySettings, form_fields
from src.app.agent_catalog.registry import REGISTRY, get_agent_definition
from src.app.audit.service import record_event
from src.app.auth.models import User, UserRole
from src.app.common.context import RequestContext
from src.app.governance.exceptions import InvalidApprovalMatrixError, PolicyNotFoundError
from src.app.governance.models import SETTINGS_ROW, AgentPolicy, ApprovalRule, OrgSettings
from src.app.governance.schemas import (
    ApprovalMatrixOut,
    ApprovalTierIn,
    ApprovalTierOut,
    Approver,
    OrgSettingsOut,
    PolicyOut,
    PolicyVersionOut,
)

# --- organization settings --------------------------------------------------------------


async def _settings(session: AsyncSession, *, lock: bool = False) -> OrgSettings:
    row = await session.get(OrgSettings, SETTINGS_ROW, with_for_update=lock)
    if row is None:
        row = OrgSettings(id=SETTINGS_ROW)
        session.add(row)
        await session.flush()
    return row


async def allow_self_approval(session: AsyncSession) -> bool:
    row = await session.get(OrgSettings, SETTINGS_ROW)
    return True if row is None else row.allow_admin_self_approval


async def get_settings(session: AsyncSession) -> OrgSettingsOut:
    row = await session.get(OrgSettings, SETTINGS_ROW)
    if row is None:
        return OrgSettingsOut(allow_admin_self_approval=True, updated_at=None)
    return OrgSettingsOut(
        allow_admin_self_approval=row.allow_admin_self_approval, updated_at=row.updated_at
    )


async def update_settings(
    session: AsyncSession, allow: bool, actor: User, ctx: RequestContext
) -> OrgSettingsOut:
    row = await _settings(session, lock=True)
    if row.allow_admin_self_approval != allow:
        row.allow_admin_self_approval = allow
        row.updated_by = actor.id
        record_event(
            session, "governance.settings_updated", ctx, actor_id=actor.id, self_approval=allow
        )
    await session.commit()
    return OrgSettingsOut(allow_admin_self_approval=allow, updated_at=row.updated_at)


# --- thresholds (versioned policies) ----------------------------------------------------


@dataclass(frozen=True)
class PolicyInForce:
    label: str  # stored on runs as policy_version
    values: PolicySettings


def _definition(key: str) -> type[BaseAgent]:
    definition = get_agent_definition(key)
    if definition is None or definition.policy_schema is None or not definition.has_workspace():
        raise PolicyNotFoundError
    return definition


def _label(key: str, version: int) -> str:
    return f"{key}/v{version}"


async def _latest(session: AsyncSession, key: str) -> AgentPolicy | None:
    return await session.scalar(
        select(AgentPolicy)
        .where(AgentPolicy.agent_key == key)
        .order_by(AgentPolicy.version.desc())
        .limit(1)
    )


async def policy_in_force(session: AsyncSession, definition: type[BaseAgent]) -> PolicyInForce:
    """The thresholds an analysis uses now: the newest version, else the code defaults."""
    schema = definition.policy_schema
    latest = await _latest(session, definition.key) if schema else None
    if schema is None or latest is None:
        return PolicyInForce(definition.policy_version, schema() if schema else PolicySettings())
    return PolicyInForce(
        _label(definition.key, latest.version), schema.model_validate(latest.values)
    )


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
    return dict(rows.all())


def _version_out(
    definition: type[BaseAgent], row: AgentPolicy | None, names: dict[uuid.UUID, str]
) -> PolicyVersionOut:
    assert definition.policy_schema is not None  # noqa: S101 - checked by _definition
    if row is None:
        return PolicyVersionOut(
            version_label=definition.policy_version,
            is_default=True,
            values=definition.policy_schema().model_dump(mode="json"),
            note="Defaults defined with the agent",
            created_at=None,
            created_by=None,
        )
    return PolicyVersionOut(
        version_label=_label(definition.key, row.version),
        is_default=False,
        values=row.values,
        note=row.note,
        created_at=row.created_at,
        created_by=names.get(row.created_by) if row.created_by else None,
    )


async def list_policies(session: AsyncSession) -> list[PolicyOut]:
    out = []
    for key, definition in REGISTRY.items():
        if definition.policy_schema is None or not definition.has_workspace():
            continue
        latest = await _latest(session, key)
        names = await _names(
            session, {latest.created_by} if latest and latest.created_by else set()
        )
        out.append(
            PolicyOut(
                agent_key=key,
                agent_name=definition.short_name,
                fields=form_fields(definition.policy_schema),
                current=_version_out(definition, latest, names),
            )
        )
    return out


async def policy_history(session: AsyncSession, key: str) -> list[PolicyVersionOut]:
    """Newest first, ending with the code defaults."""
    definition = _definition(key)
    rows = list(
        await session.scalars(
            select(AgentPolicy)
            .where(AgentPolicy.agent_key == key)
            .order_by(AgentPolicy.version.desc())
        )
    )
    names = await _names(session, {r.created_by for r in rows if r.created_by})
    return [_version_out(definition, r, names) for r in rows] + [
        _version_out(definition, None, names)
    ]


async def save_policy(
    session: AsyncSession,
    key: str,
    values: dict[str, Any],
    note: str | None,
    actor: User,
    ctx: RequestContext,
) -> PolicyOut:
    """A new version (unless nothing changed). Takes effect for analyses from now on."""
    definition = _definition(key)
    assert definition.policy_schema is not None  # noqa: S101 - checked by _definition
    try:
        validated = definition.policy_schema.model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**e, "loc": ("body", "values", *e["loc"])} for e in exc.errors(include_url=False)]
        ) from exc
    new_values = validated.model_dump(mode="json")
    current = await policy_in_force(session, definition)
    if current.values.model_dump(mode="json") != new_values:
        # Lock the agent's versions so two admins saving at once can't take the same number
        await session.execute(
            select(AgentPolicy.id).where(AgentPolicy.agent_key == key).with_for_update()
        )
        latest = await session.scalar(
            select(func.max(AgentPolicy.version)).where(AgentPolicy.agent_key == key)
        )
        version = (latest or 1) + 1  # v1 is the code default
        session.add(
            AgentPolicy(
                agent_key=key,
                version=version,
                values=new_values,
                note=(note or "").strip() or None,
                created_by=actor.id,
            )
        )
        record_event(
            session,
            "governance.policy_updated",
            ctx,
            actor_id=actor.id,
            agent=key,
            version=_label(key, version),
            values=new_values,
        )
        await session.commit()
    return next(p for p in await list_policies(session) if p.agent_key == key)


# --- approval matrix --------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalRoute:
    required: int
    approver_ids: list[uuid.UUID]  # empty = any Finance Admin
    min_amount: Decimal | None  # matched tier (None: no matrix for this agent)
    amount: Decimal | None

    def snapshot(self) -> dict[str, Any]:
        return {
            "amount": None if self.amount is None else str(self.amount),
            "min_amount": None if self.min_amount is None else str(self.min_amount),
            "approvals_required": self.required,
            "approver_ids": [str(i) for i in self.approver_ids],
        }


async def _rules(session: AsyncSession, key: str) -> list[ApprovalRule]:
    return list(
        await session.scalars(
            select(ApprovalRule)
            .where(ApprovalRule.agent_key == key)
            .order_by(ApprovalRule.min_amount)
        )
    )


async def route_for(session: AsyncSession, key: str, amount: Decimal | None) -> ApprovalRoute:
    """The highest tier whose minimum the amount reaches (no amount: the lowest tier)."""
    rules = await _rules(session, key)
    if not rules:
        return ApprovalRoute(1, [], None, amount)
    matched = rules[0]
    for rule in rules:
        if amount is not None and amount >= rule.min_amount:
            matched = rule
    if amount is not None and amount < rules[0].min_amount:
        return ApprovalRoute(1, [], None, amount)  # below every tier: default routing
    return ApprovalRoute(
        matched.approvals_required,
        [uuid.UUID(i) for i in matched.approver_ids],
        matched.min_amount,
        amount,
    )


def _workspace_agent(key: str) -> type[BaseAgent]:
    definition = get_agent_definition(key)
    if definition is None or not definition.has_workspace():
        raise PolicyNotFoundError("This agent has no workspace to route approvals for.")
    return definition


async def _admins(session: AsyncSession) -> dict[uuid.UUID, str]:
    rows = await session.execute(
        select(User.id, User.full_name).where(
            User.role == UserRole.FINANCE_ADMIN, User.is_active.is_(True)
        )
    )
    return dict(rows.all())


async def get_matrix(session: AsyncSession, key: str) -> ApprovalMatrixOut:
    definition = _workspace_agent(key)
    rules = await _rules(session, key)
    names = await _names(session, {uuid.UUID(i) for r in rules for i in r.approver_ids})
    return ApprovalMatrixOut(
        agent_key=key,
        agent_name=definition.short_name,
        amount_label=definition.approval_amount_label,
        tiers=[
            ApprovalTierOut(
                min_amount=r.min_amount,
                approvals_required=r.approvals_required,
                approvers=[
                    Approver(id=uuid.UUID(i), full_name=names.get(uuid.UUID(i), "Deleted user"))
                    for i in r.approver_ids
                ],
            )
            for r in rules
        ],
    )


async def list_matrices(session: AsyncSession) -> list[ApprovalMatrixOut]:
    return [
        await get_matrix(session, key)
        for key, definition in REGISTRY.items()
        if definition.has_workspace()
    ]


async def set_matrix(
    session: AsyncSession,
    key: str,
    tiers: list[ApprovalTierIn],
    actor: User,
    ctx: RequestContext,
) -> ApprovalMatrixOut:
    """Replace the agent's tiers. Runs already submitted keep the tier they got."""
    _workspace_agent(key)
    if len({t.min_amount for t in tiers}) != len(tiers):
        raise InvalidApprovalMatrixError("Each tier needs a different starting amount.")
    admins = await _admins(session)
    for t in sorted(tiers, key=lambda t: t.min_amount):
        approvers = set(t.approver_ids)
        if approvers - admins.keys():
            raise InvalidApprovalMatrixError("Approvers must be active Finance Admins.")
        pool = len(approvers) if approvers else len(admins)
        if t.approvals_required > pool:
            raise InvalidApprovalMatrixError(
                f"The tier from {t.min_amount:,.2f} needs {t.approvals_required} approvals but "
                f"only {pool} Finance Admin(s) can approve it."
            )
    await session.execute(delete(ApprovalRule).where(ApprovalRule.agent_key == key))
    session.add_all(
        ApprovalRule(
            agent_key=key,
            min_amount=t.min_amount,
            approvals_required=t.approvals_required,
            approver_ids=sorted({str(i) for i in t.approver_ids}),
        )
        for t in tiers
    )
    record_event(
        session,
        "governance.approval_matrix_updated",
        ctx,
        actor_id=actor.id,
        agent=key,
        tiers=[
            {
                "min_amount": str(t.min_amount),
                "approvals_required": t.approvals_required,
                "approvers": len(t.approver_ids),
            }
            for t in sorted(tiers, key=lambda t: t.min_amount)
        ],
    )
    await session.commit()
    return await get_matrix(session, key)
