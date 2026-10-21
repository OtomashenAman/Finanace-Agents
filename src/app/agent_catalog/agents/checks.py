"""Reusable deterministic checks for agents' analyze(): each returns Findings, never calls the LLM.

Agents keep their own codes and wording; these helpers only remove the repeated branching
(match / within tolerance / mismatch, over a limit, duplicate run, missing evidence).
"""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select

from src.app.agent_catalog.agents.base import AnalysisContext, Finding
from src.app.agent_catalog.runs.models import AgentRun, AgentRunDetail, FlagSeverity, RunStatus

ZERO = Decimal("0.00")


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def percent(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def ratio_pct(part: Decimal | int, whole: Decimal | int) -> Decimal | None:
    """part / whole as a percentage rounded to 2 places (8.00 for 2 of 25); None if whole is 0."""
    if not whole:
        return None
    return (Decimal(part) / Decimal(whole) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


def has_severity(findings: Iterable[Finding], severity: FlagSeverity) -> bool:
    return any(f.severity == severity for f in findings)


def tolerance_check(
    difference: Decimal,
    tolerance: Decimal,
    *,
    subject: str,
    other: str,
    tolerance_name: str,
    match_code: str,
    mismatch_code: str,
    field: str | None = None,
    severity: FlagSeverity = FlagSeverity.HIGH,
) -> Finding:
    """Pass on an exact match or a difference within tolerance, else `severity`.

    e.g. subject="Invoice total", other="the PO authorized amount", tolerance_name="PO".
    """
    if difference == ZERO:
        return Finding(match_code, FlagSeverity.PASS, f"{subject} matches {other}", field)
    if abs(difference) <= tolerance:
        return Finding(
            match_code,
            FlagSeverity.PASS,
            f"{subject} is within the {money(tolerance)} {tolerance_name} tolerance "
            f"(difference {money(difference)})",
            field,
        )
    return Finding(
        mismatch_code, severity, f"{subject} differs from {other} by {money(difference)}", field
    )


def over_limit(
    value: Decimal | int | None,
    limit: Decimal | int | None,
    *,
    code: str,
    message: str,
    field: str | None = None,
    severity: FlagSeverity = FlagSeverity.WARNING,
) -> Finding | None:
    """A finding when value is above limit; None when within it, or either is None (an empty
    optional input, or a threshold that is turned off)."""
    if value is None or limit is None or value <= limit:
        return None
    return Finding(code, severity, message, field)


def missing(
    value: Any,
    *,
    code: str,
    message: str,
    field: str | None = None,
    severity: FlagSeverity = FlagSeverity.WARNING,
) -> Finding | None:
    """A finding when an optional input was left empty."""
    if value is not None and value != "":
        return None
    return Finding(code, severity, message, field)


def evidence_check(
    ctx: AnalysisContext,
    documents: str,
    *,
    severity: FlagSeverity = FlagSeverity.WARNING,
) -> Finding | None:
    """A finding when the run has no documents attached, e.g. documents="invoice, PO or receipt"."""
    if ctx.document_count:
        return None
    return Finding("MISSING_EVIDENCE", severity, f"No supporting documents attached ({documents})")


async def earlier_run(
    ctx: AnalysisContext, run_model: type[AgentRunDetail], **match: Any
) -> int | None:
    """Run number of the preparer's earliest analyzed run with the same values (text compared
    case-insensitively), or None. Each user's runs are isolated: only their own runs count."""
    conditions = []
    for name, value in match.items():
        column = getattr(run_model, name)
        if isinstance(value, str):
            conditions.append(func.lower(column) == value.lower())
        else:
            conditions.append(column == value)
    return await ctx.session.scalar(
        select(AgentRun.run_number)
        .join(run_model, run_model.run_id == AgentRun.id)
        .where(
            AgentRun.id != ctx.run.id,
            AgentRun.preparer_id == ctx.run.preparer_id,
            AgentRun.status.not_in([RunStatus.DRAFT, RunStatus.VALIDATION_FAILED]),
            *conditions,
        )
        .order_by(AgentRun.run_number)
        .limit(1)
    )


async def duplicate_check(
    ctx: AnalysisContext,
    run_model: type[AgentRunDetail],
    *,
    what: str,
    duplicate_code: str,
    clear_code: str,
    field: str | None = None,
    **match: Any,
) -> tuple[Finding, int | None]:
    """HIGH if an earlier run has the same values, else a pass; also returns that run number.

    e.g. what="supplier and invoice number", supplier=..., invoice_number=...
    """
    duplicate_of = await earlier_run(ctx, run_model, **match)
    if duplicate_of is not None:
        return (
            Finding(
                duplicate_code,
                FlagSeverity.HIGH,
                f"Same {what} already analyzed in RUN-{duplicate_of:05d}",
                field,
            ),
            duplicate_of,
        )
    return (
        Finding(clear_code, FlagSeverity.PASS, f"No earlier run with this {what}", field),
        None,
    )
