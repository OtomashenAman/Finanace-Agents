from typing import cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
)
from src.app.agent_catalog.agents.board_reporting import prompt
from src.app.agent_catalog.agents.board_reporting.models import BoardReportingRun
from src.app.agent_catalog.agents.board_reporting.schemas import (
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
from src.app.agent_catalog.runs.models import FlagSeverity


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
