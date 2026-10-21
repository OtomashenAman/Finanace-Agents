from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
)
from src.app.agent_catalog.agents.checks import (
    evidence_check,
    has_severity,
    money,
    percent,
    ratio_pct,
)
from src.app.agent_catalog.agents.fpa_forecast import prompt
from src.app.agent_catalog.agents.fpa_forecast.models import FpaForecastRun
from src.app.agent_catalog.agents.fpa_forecast.schemas import FpaForecastInput, FpaForecastPolicy
from src.app.agent_catalog.runs.models import FlagSeverity

CENT = Decimal("0.01")


def _pct_of(value: Decimal, pct: Decimal) -> Decimal:
    return (value * pct / 100).quantize(CENT, ROUND_HALF_UP)


class FpaForecastAgent(BaseAgent):
    key = "fpa_forecast"
    code = "07"
    name = "FP&A Forecast, Variance & Scenario Planning"
    short_name = "FP&A"
    description = "Evaluate actual/budget differences and parameterized scenarios."
    primary_user = "FP&A Analyst"
    reviewer = "FP&A Manager"

    input_schema = FpaForecastInput
    run_model = FpaForecastRun
    reference_field = "business_unit"
    policy_version = "fpa_forecast/v1"
    controls = (
        "Variance materiality",
        "Assumption approval",
        "Scenario version control",
        "Narrative source trace",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    policy_schema = FpaForecastPolicy
    approval_amount_label = "Absolute variance"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        plan = cast(FpaForecastInput, data)
        return abs(plan.actual_value - plan.budget_value)

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        plan = cast(FpaForecastInput, data)
        policy = cast(FpaForecastPolicy, ctx.policy) if ctx.policy else FpaForecastPolicy()
        variance = plan.actual_value - plan.budget_value
        variance_pct = ratio_pct(variance, abs(plan.budget_value))

        # Scenario bridge: volume, then price on the new volume, then cost on the actual
        volume_impact = _pct_of(plan.actual_value, plan.scenario_volume_pct)
        price_impact = _pct_of(plan.actual_value + volume_impact, plan.scenario_price_pct)
        cost_impact = -_pct_of(plan.actual_value, plan.scenario_cost_pct)
        scenario = plan.actual_value + volume_impact + price_impact + cost_impact
        findings: list[Finding] = []

        materiality = policy.variance_materiality_pct
        if variance_pct is None:
            findings.append(
                Finding(
                    "NO_BUDGET",
                    FlagSeverity.WARNING,
                    "Budget value is zero: the variance % can't be calculated",
                    "budget_value",
                )
            )
        elif materiality is not None and abs(variance_pct) > materiality:
            findings.append(
                Finding(
                    "VARIANCE_MATERIAL",
                    FlagSeverity.HIGH,
                    f"Actual vs budget variance of {money(variance)} ({percent(variance_pct)}) "
                    f"exceeds the {percent(materiality)} materiality threshold",
                    "actual_value",
                )
            )
        else:
            findings.append(
                Finding(
                    "VARIANCE_WITHIN_THRESHOLD",
                    FlagSeverity.PASS,
                    f"Actual vs budget variance is {percent(variance_pct)}",
                    "actual_value",
                )
            )

        limit = policy.scenario_review_pct
        drivers = {
            "scenario_volume_pct": ("volume", plan.scenario_volume_pct),
            "scenario_price_pct": ("price", plan.scenario_price_pct),
            "scenario_cost_pct": ("cost", plan.scenario_cost_pct),
        }
        for field, (label, value) in drivers.items():
            if limit is not None and abs(value) > limit:
                findings.append(
                    Finding(
                        "UNUSUAL_SCENARIO",
                        FlagSeverity.WARNING,
                        f"Scenario {label} change of {percent(value)} is beyond the "
                        f"{percent(limit)} review limit",
                        field,
                    )
                )

        if plan.planning_assumptions:
            findings.append(
                Finding(
                    "ASSUMPTION_APPROVAL",
                    FlagSeverity.INFO,
                    "Planning assumptions need FP&A manager approval",
                    "planning_assumptions",
                )
            )
        else:
            findings.append(
                Finding(
                    "MISSING_ASSUMPTIONS",
                    FlagSeverity.WARNING,
                    "No planning assumptions: the scenario drivers can't be traced",
                    "planning_assumptions",
                )
            )
        evidence = evidence_check(ctx, "actuals report or approved budget")
        if evidence is not None:
            findings.append(evidence)
        findings.append(
            Finding(
                "SCENARIO_VERSION",
                FlagSeverity.INFO,
                f"Scenario drivers (volume {percent(plan.scenario_volume_pct)}, price "
                f"{percent(plan.scenario_price_pct)}, cost {percent(plan.scenario_cost_pct)}) "
                "are recorded with this run",
            )
        )

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if exceptions:
            headline = "Budget variance"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Forecast needs review"
        else:
            headline = "Within budget tolerance"

        return Analysis(
            headline=headline,
            proposed_decision=(
                "Explain the variance and approve the scenario assumptions"
                if exceptions
                else "Scenario assumptions for approval"
            ),
            calculations=[
                Calculation("actual_value", "Actual value", plan.actual_value),
                Calculation("budget_value", "Budget value", plan.budget_value),
                Calculation("variance", "Variance (actual - budget)", variance),
                Calculation("variance_pct", "Variance %", variance_pct, "percent"),
                Calculation("volume_impact", "Scenario volume impact", volume_impact),
                Calculation("price_impact", "Scenario price impact", price_impact),
                Calculation("cost_impact", "Scenario cost impact", cost_impact),
                Calculation("scenario_value", "Scenario value", scenario),
            ],
            findings=findings,
            computed={
                "variance": variance,
                "variance_pct": variance_pct,
                "scenario_value": scenario,
            },
        )
