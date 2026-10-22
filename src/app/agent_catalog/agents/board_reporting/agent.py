from typing import cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
    Prefill,
)
from src.app.agent_catalog.agents.board_reporting import prompt
from src.app.agent_catalog.agents.board_reporting.models import BoardReportingRun
from src.app.agent_catalog.agents.board_reporting.schemas import (
    BoardPrefillParams,
    BoardReportingInput,
    BoardReportingPolicy,
)
from src.app.agent_catalog.agents.checks import (
    ZERO,
    evidence_check,
    has_severity,
    missing,
    percent,
    ratio_pct,
)
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.agents.periods import (
    months_of,
    period_end,
    period_options,
    same_period_last_year,
)
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource, SourceKind
from src.app.data_sources.records import PeriodResult, RecordType


async def company_actuals(data: FinanceData) -> dict[str, PeriodResult]:
    """The company's actual P&L by month (business units left out)."""
    results = await data.records(PeriodResult, RecordType.PERIOD_RESULT)
    return {r.period: r for r in results if r.basis == "actual" and r.business_unit is None}


def covering(by_month: dict[str, PeriodResult], period: str | None) -> list[PeriodResult] | None:
    """The months of `period`, if every one of them is in the data."""
    months = months_of(period) if period else None
    if not months or any(m not in by_month for m in months):
        return None
    return [by_month[m] for m in months]


def source_reference(source: DataSource | None, period: str) -> str | None:
    """e.g. "QuickBooks Acme Ltd: P&L 2026-Q3, data as of 2026-10-21 09:30 UTC"."""
    if source is None:
        return None
    as_of = source.history_synced_at or source.last_synced_at
    kind = "QuickBooks" if source.kind == SourceKind.QUICKBOOKS else "Upload"
    stamp = f", data as of {as_of:%Y-%m-%d %H:%M} UTC" if as_of else ""
    return f"{kind} {source.name}: P&L {period}{stamp}"[:200]


class BoardReportingAgent(BaseAgent):
    key = "board_reporting"
    code = "12"
    name = "Financial Reporting, Disclosure & Board Pack"
    short_name = "Board Reporting"
    description = "Generate grounded disclosure and board commentary from approved metrics."
    primary_user = "Reporting Analyst"
    reviewer = "CFO / Controller"

    input_schema = BoardReportingInput
    run_model = BoardReportingRun
    reference_field = "report_name"
    policy_version = "board_reporting/v1"
    controls = (
        "Approved source references",
        "Numerical consistency",
        "Disclosure control",
        "CFO sign-off",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    policy_schema = BoardReportingPolicy
    prefill_params = BoardPrefillParams

    @classmethod
    async def prefill_options(cls, data: FinanceData) -> dict[str, list[str]]:
        return {"reporting_period": period_options(set(await company_actuals(data)))}

    @classmethod
    async def prefill_from_data(
        cls, params: BaseModel, data: FinanceData, policy: PolicySettings | None = None
    ) -> Prefill:
        period = cast(BoardPrefillParams, params).reporting_period.strip()
        prior_period = same_period_last_year(period)
        by_month = await company_actuals(data)
        current = covering(by_month, period)
        prior = covering(by_month, prior_period)
        values: dict[str, object] = {"reporting_period": period}
        summary: dict[str, object] = {"compared_with": prior_period}
        if current is None:
            summary["reported"] = f"Not every month of {period} is in the data"
        else:
            revenue = sum((r.revenue for r in current), ZERO)
            values["reported_revenue"] = revenue if revenue >= ZERO else None
            values["operating_profit"] = sum((r.operating_profit or ZERO for r in current), ZERO)
            values["source_dataset_id"] = source_reference(await data.primary_source(), period)
        if prior is None:
            summary["prior"] = f"Not every month of {prior_period} is in the data"
        else:
            prior_revenue = sum((r.revenue for r in prior), ZERO)
            values["prior_period_revenue"] = prior_revenue if prior_revenue >= ZERO else None
        return Prefill(
            {k: v for k, v in values.items() if v is not None},
            reference=f"{period} vs {prior_period}",
            summary=summary,
            lines={"months": current or [], "prior_year_months": prior or []},
        )

    @staticmethod
    async def _period_checks(report: BoardReportingInput, ctx: AnalysisContext) -> list[Finding]:
        """Against the books closing date of the preparer's QuickBooks, when known."""
        closed = await ctx.data.books_closed_through()
        end = period_end(report.reporting_period)
        if closed is None or end is None:
            return []
        if end > closed:
            return [
                Finding(
                    "PERIOD_NOT_CLOSED",
                    FlagSeverity.WARNING,
                    f"Books are closed through {closed:%d %b %Y}: {report.reporting_period} is "
                    "not fully closed, so its figures can still change",
                    "reporting_period",
                )
            ]
        return [
            Finding(
                "PERIOD_CLOSED",
                FlagSeverity.PASS,
                f"{report.reporting_period} is closed in the books (closed through "
                f"{closed:%d %b %Y})",
                "reporting_period",
            )
        ]

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        report = cast(BoardReportingInput, data)
        policy = cast(BoardReportingPolicy, ctx.policy) if ctx.policy else BoardReportingPolicy()
        change = report.reported_revenue - report.prior_period_revenue
        growth = ratio_pct(change, report.prior_period_revenue)
        margin = ratio_pct(report.operating_profit, report.reported_revenue)
        findings: list[Finding] = []

        if report.source_dataset_id:
            findings.append(
                Finding(
                    "SOURCE_REFERENCED",
                    FlagSeverity.PASS,
                    f"Figures reference approved source {report.source_dataset_id}",
                    "source_dataset_id",
                )
            )
        else:
            findings.append(
                Finding(
                    "MISSING_SOURCE_REFERENCE",
                    FlagSeverity.HIGH,
                    "No approved source dataset or approval ID: board figures must trace to "
                    "approved metrics",
                    "source_dataset_id",
                )
            )

        consistent = True
        if report.operating_profit > report.reported_revenue:
            consistent = False
            findings.append(
                Finding(
                    "PROFIT_EXCEEDS_REVENUE",
                    FlagSeverity.HIGH,
                    "Operating profit is greater than reported revenue",
                    "operating_profit",
                )
            )
        if report.prior_period_revenue == ZERO:
            consistent = False
            findings.append(
                Finding(
                    "NO_PRIOR_PERIOD",
                    FlagSeverity.WARNING,
                    "Prior period revenue is zero: growth can't be calculated",
                    "prior_period_revenue",
                )
            )
        elif (
            growth is not None
            and policy.revenue_change_review_pct is not None
            and abs(growth) > policy.revenue_change_review_pct
        ):
            consistent = False
            findings.append(
                Finding(
                    "UNUSUAL_REVENUE_CHANGE",
                    FlagSeverity.WARNING,
                    f"Revenue changed {percent(growth)} vs the prior period, beyond the "
                    f"{percent(policy.revenue_change_review_pct)} review threshold: confirm "
                    "the explanation",
                    "reported_revenue",
                )
            )
        if consistent:
            findings.append(
                Finding(
                    "NUMBERS_CONSISTENT",
                    FlagSeverity.PASS,
                    "Revenue, prior period and operating profit are numerically consistent",
                    "reported_revenue",
                )
            )

        findings.extend(await cls._period_checks(report, ctx))
        optional_checks = [
            missing(
                report.known_disclosures,
                code="NO_DISCLOSURES_RECORDED",
                message="No known disclosures recorded: confirm none apply",
                field="known_disclosures",
            ),
            evidence_check(ctx, "approved financials or close package"),
        ]
        findings.extend(f for f in optional_checks if f is not None)
        findings.append(
            Finding(
                "CFO_SIGN_OFF",
                FlagSeverity.INFO,
                "CFO / Controller sign-off is required before anything is released",
            )
        )

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if not report.source_dataset_id:
            headline = "Source references missing"
        elif exceptions:
            headline = "Board figures inconsistent"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Board pack needs review"
        else:
            headline = "Board figures consistent"

        verb = "increased" if change >= ZERO else "decreased"
        calculations = [
            Calculation("reported_revenue", "Reported revenue", report.reported_revenue),
            Calculation(
                "prior_period_revenue", "Prior period revenue", report.prior_period_revenue
            ),
            Calculation("revenue_change", f"Revenue {verb} by", change),
            Calculation("revenue_growth_pct", "Revenue growth", growth, "percent"),
            Calculation("operating_profit", "Operating profit", report.operating_profit),
            Calculation("operating_margin_pct", "Operating margin", margin, "percent"),
        ]
        return Analysis(
            headline=headline,
            proposed_decision=(
                "Resolve source and consistency issues before sign-off"
                if exceptions
                else "Approve all source claims and disclosures"
            ),
            calculations=calculations,
            findings=findings,
            computed={
                "revenue_change": change,
                "revenue_growth_pct": growth,
                "operating_margin_pct": margin,
            },
        )
