"""The budget agent (Phase 1.2.1): runs on every submission, deterministic.

a. budget impact: each request line is charged to the most specific budget line of the
   fiscal year (the grant's, or else the cost centre's; its category's line, or else the
   whole-holder line). Available = budget - committed - spent - requests already approved
   in the Finance POD. Over budget or no budget line: an approver may still approve, with
   a note.
b. grant allowability: a category the grant doesn't allow, or a needed-by date outside the
   grant period, blocks approval; a line without a category needs the approver to confirm.
c. routing: the budget owner first (the grant's principal investigator for grant-funded
   requests, else the cost centre's owner), then every authority-matrix tier the total
   reaches. Tiers for the request's cost centre replace the general ones.

The fiscal year is the needed-by date's calendar year.
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.auth.models import User
from src.app.common.clock import utcnow
from src.app.finance_pod.access import finance_pod_people
from src.app.finance_pod.approvals.models import FpCommitment
from src.app.finance_pod.approvals.schemas import BudgetCheck, BudgetImpact, Finding, RouteStep
from src.app.finance_pod.reference.models import (
    AuthorityScope,
    FpAuthorityTier,
    FpBudget,
    FpCostCentre,
    FpGrant,
)
from src.app.finance_pod.requests.models import FpPurchaseRequest

ZERO = Decimal("0.00")


def _pick(budgets: dict[str | None, FpBudget], category: str | None) -> FpBudget | None:
    """The category's own line, else the line for the whole holder."""
    if category and category in budgets:
        return budgets[category]
    return budgets.get(None)


async def _impacts(
    session: AsyncSession,
    request: FpPurchaseRequest,
    grant: FpGrant | None,
    fiscal_year: int,
) -> tuple[list[BudgetImpact], list[Finding]]:
    if grant is not None:
        holder_label, where = f"grant {grant.code}", FpBudget.grant_code == grant.code
    else:
        code = request.cost_centre_code or ""
        holder_label, where = f"cost centre {code}", FpBudget.cost_centre_code == code
    rows = await session.scalars(select(FpBudget).where(where, FpBudget.fiscal_year == fiscal_year))
    budgets = {b.category: b for b in rows}

    charged: dict[object, list[int]] = defaultdict(list)  # budget id, or ("none", category)
    amounts: dict[object, Decimal] = defaultdict(lambda: ZERO)
    picked: dict[object, FpBudget | None] = {}
    for n, line in enumerate(request.lines, start=1):
        budget = _pick(budgets, line.category)
        key: object = budget.id if budget else ("none", line.category)
        picked[key] = budget
        charged[key].append(n)
        amounts[key] += line.amount

    ids = [b.id for b in picked.values() if b is not None]
    held: dict[object, Decimal] = {}
    if ids:
        sums = await session.execute(
            select(FpCommitment.budget_id, func.sum(FpCommitment.amount))
            .where(
                FpCommitment.budget_id.in_(ids),
                FpCommitment.released_at.is_(None),
                FpCommitment.request_id != request.id,
            )
            .group_by(FpCommitment.budget_id)
        )
        held = dict(sums.all())

    impacts, findings = [], []
    for key, lines in charged.items():
        budget = picked[key]
        this = amounts[key]
        if budget is None:
            category = key[1] if isinstance(key, tuple) else None
            findings.append(
                Finding(
                    kind="no_budget",
                    message=(
                        f"No {fiscal_year} budget for {holder_label}"
                        + (f" ({category})" if category else "")
                        + f": lines {', '.join(map(str, lines))}."
                    ),
                    severity="acknowledge",
                )
            )
            impacts.append(
                BudgetImpact(
                    budget_id=None,
                    holder=holder_label,
                    fiscal_year=fiscal_year,
                    category=category,
                    lines=lines,
                    budget=ZERO,
                    committed=ZERO,
                    spent=ZERO,
                    approved_requests=ZERO,
                    available=ZERO,
                    this_request=this,
                    remaining_after=-this,
                    over_budget=this > 0,
                )
            )
            continue
        approved = held.get(budget.id, ZERO)
        available = budget.amount - budget.committed - budget.spent - approved
        after = available - this
        if after < 0:
            findings.append(
                Finding(
                    kind="over_budget",
                    message=(
                        f"Over the {fiscal_year} budget of {holder_label}"
                        + (f" ({budget.category})" if budget.category else "")
                        + f" by {-after:,.2f} {request.currency}."
                    ),
                    severity="acknowledge",
                )
            )
        impacts.append(
            BudgetImpact(
                budget_id=budget.id,
                holder=holder_label,
                fiscal_year=fiscal_year,
                category=budget.category,
                lines=lines,
                budget=budget.amount,
                committed=budget.committed,
                spent=budget.spent,
                approved_requests=approved,
                available=available,
                this_request=this,
                remaining_after=after,
                over_budget=after < 0,
            )
        )
    return impacts, findings


def _grant_findings(request: FpPurchaseRequest, grant: FpGrant | None) -> list[Finding]:
    if grant is None:
        if request.grant_code:
            return [
                Finding(
                    kind="unallowable",
                    message=f"Grant {request.grant_code} doesn't exist.",
                    severity="blocking",
                )
            ]
        return []
    found = []
    when = request.needed_by or utcnow().date()
    if not grant.active:
        found.append(
            Finding(
                kind="grant_period",
                message=f"Grant {grant.code} is no longer active.",
                severity="blocking",
            )
        )
    if (grant.start_date and when < grant.start_date) or (grant.end_date and when > grant.end_date):
        found.append(
            Finding(
                kind="grant_period",
                message=(
                    f"Needed by {when.isoformat()}, outside grant {grant.code}'s period "
                    f"({grant.start_date or '?'} to {grant.end_date or '?'})."
                ),
                severity="blocking",
            )
        )
    for n, line in enumerate(request.lines, start=1):
        if line.category is None:
            found.append(
                Finding(
                    kind="uncategorised",
                    message=(
                        f"Line {n} has no category, so grant {grant.code}'s rules couldn't be "
                        "checked: confirm it is allowable."
                    ),
                    severity="acknowledge",
                )
            )
        elif line.category in grant.unallowable_categories:
            found.append(
                Finding(
                    kind="unallowable",
                    message=f"Line {n}: grant {grant.code} doesn't allow '{line.category}'.",
                    severity="blocking",
                )
            )
    return found


async def _route(
    session: AsyncSession, request: FpPurchaseRequest, grant: FpGrant | None
) -> tuple[list[RouteStep], list[Finding]]:
    total = request.total
    owner, capacity = None, "Budget owner"
    if grant is not None and grant.owner_email:
        owner, capacity = grant.owner_email, "Budget owner (grant PI)"
    else:
        cc = await session.scalar(
            select(FpCostCentre).where(FpCostCentre.code == (request.cost_centre_code or ""))
        )
        if cc is not None and cc.owner_email:
            owner = cc.owner_email

    tiers = list(
        await session.scalars(
            select(FpAuthorityTier)
            .where(FpAuthorityTier.scope == AuthorityScope.REQUEST)
            .order_by(FpAuthorityTier.min_amount)
        )
    )
    specific = [t for t in tiers if t.cost_centre_code == request.cost_centre_code]
    applicable = [
        t
        for t in (specific or [t for t in tiers if t.cost_centre_code is None])
        if t.min_amount <= total
    ]

    steps: list[tuple[str, str, Decimal]] = []
    if owner:
        steps.append((owner, capacity, ZERO))
    for t in applicable:
        if t.approver_email not in {s[0] for s in steps}:
            steps.append((t.approver_email, t.capacity, t.min_amount))
    if not steps:
        return [], [
            Finding(
                kind="routing",
                message=(
                    f"Nobody to approve: give cost centre {request.cost_centre_code} a budget "
                    "owner, or add request tiers to the authority matrix."
                ),
                severity="blocking",
            )
        ]

    names = {
        email.lower(): name
        for email, name in await session.execute(
            select(User.email, User.full_name).where(
                func.lower(User.email).in_([s[0].lower() for s in steps]),
                finance_pod_people(),
            )
        )
    }
    route = [
        RouteStep(
            step=i,
            capacity=cap,
            approver_email=email,
            approver_name=names.get(email.lower()),
            min_amount=min_amount,
            status="pending",
        )
        for i, (email, cap, min_amount) in enumerate(steps, start=1)
    ]
    findings = [
        Finding(
            kind="routing",
            message=(
                f"{s.approver_email} ({s.capacity}) has no Finance Admin account: another "
                "Finance Admin can decide for them, and it's recorded that way."
            ),
            severity="info",
        )
        for s in route
        if s.approver_name is None
    ]
    return route, findings


async def check(session: AsyncSession, request: FpPurchaseRequest) -> BudgetCheck:
    fiscal_year = (request.needed_by or utcnow().date()).year
    grant = None
    if request.grant_code:
        grant = await session.scalar(select(FpGrant).where(FpGrant.code == request.grant_code))
    impacts, budget_findings = await _impacts(session, request, grant, fiscal_year)
    route, route_findings = await _route(session, request, grant)
    return BudgetCheck(
        ran_at=utcnow(),
        round=request.round,
        total=request.total,
        currency=request.currency,
        fiscal_year=fiscal_year,
        impacts=impacts,
        findings=[*_grant_findings(request, grant), *budget_findings, *route_findings],
        route=route,
    )
