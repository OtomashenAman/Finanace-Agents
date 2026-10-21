from decimal import Decimal
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
    ZERO,
    evidence_check,
    has_severity,
    missing,
    money,
    over_limit,
)
from src.app.agent_catalog.agents.treasury_cash import prompt
from src.app.agent_catalog.agents.treasury_cash.models import TreasuryCashRun
from src.app.agent_catalog.agents.treasury_cash.schemas import (
    TreasuryCashInput,
    TreasuryCashPolicy,
)
from src.app.agent_catalog.runs.models import FlagSeverity


def _closing_cash(data: TreasuryCashInput) -> Decimal:
    return data.opening_cash + data.expected_inflows - data.expected_outflows


def _funding_gap(data: TreasuryCashInput) -> Decimal:
    """How much must be funded to stay at the buffer (0 when the buffer holds)."""
    return max(data.minimum_liquidity_buffer - _closing_cash(data), ZERO)


class TreasuryCashAgent(BaseAgent):
    key = "treasury_cash"
    code = "08"
    name = "Treasury Cash Forecasting & Liquidity"
    short_name = "Treasury"
    description = "Forecast end cash and detect shortfalls before funds movement."
    primary_user = "Treasury Analyst"
    reviewer = "Treasury Approver"

    input_schema = TreasuryCashInput
    run_model = TreasuryCashRun
    policy_version = "treasury_cash/v1"
    controls = (
        "Liquidity buffer",
        "Negative projected cash",
        "Dual authorization",
        "Bank signatories",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    policy_schema = TreasuryCashPolicy
    approval_amount_label = "Funding gap"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return _funding_gap(cast(TreasuryCashInput, data))

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        cash = cast(TreasuryCashInput, data)
        policy = cast(TreasuryCashPolicy, ctx.policy) if ctx.policy else TreasuryCashPolicy()
        closing = _closing_cash(cash)
        gap = _funding_gap(cash)
        buffer = cash.minimum_liquidity_buffer
        findings: list[Finding] = []

        if closing < ZERO:
            findings.append(
                Finding(
                    "NEGATIVE_PROJECTED_CASH",
                    FlagSeverity.HIGH,
                    f"Projected closing cash is negative ({money(closing)}) within "
                    f"{cash.forecast_horizon_days} days",
                    "expected_outflows",
                )
            )
        else:
            findings.append(
                Finding(
                    "PROJECTED_CASH_POSITIVE",
                    FlagSeverity.PASS,
                    f"Projected closing cash stays positive ({money(closing)})",
                    "expected_outflows",
                )
            )

        if gap > ZERO:
            findings.append(
                Finding(
                    "LIQUIDITY_BUFFER",
                    FlagSeverity.HIGH,
                    f"Projected closing cash {money(closing)} is {money(gap)} below the "
                    f"{money(buffer)} minimum liquidity buffer",
                    "minimum_liquidity_buffer",
                )
            )
            dual = over_limit(
                gap,
                policy.dual_authorization_amount,
                code="DUAL_AUTHORIZATION",
                message=(
                    f"Funding the {money(gap)} gap needs dual authorization by the bank "
                    "signatories before any funds move"
                ),
                field="minimum_liquidity_buffer",
            )
            no_options = missing(
                cash.permitted_funding_options,
                code="NO_FUNDING_OPTIONS",
                message="No permitted funding options recorded for the shortfall",
                field="permitted_funding_options",
            )
            findings.extend(f for f in (dual, no_options) if f is not None)
        else:
            findings.append(
                Finding(
                    "LIQUIDITY_BUFFER_MET",
                    FlagSeverity.PASS,
                    f"Projected closing cash covers the {money(buffer)} minimum liquidity "
                    f"buffer (headroom {money(closing - buffer)})",
                    "minimum_liquidity_buffer",
                )
            )

        optional_checks = [
            over_limit(
                cash.expected_outflows,
                policy.large_outflow_amount,
                code="LARGE_OUTFLOWS",
                message=(
                    f"Expected outflows exceed the {money(policy.large_outflow_amount or ZERO)} "
                    "review limit: confirm their timing"
                ),
                field="expected_outflows",
            ),
            evidence_check(ctx, "bank statements or cash forecast"),
        ]
        findings.extend(f for f in optional_checks if f is not None)

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if closing < ZERO:
            headline = "Negative cash projected"
        elif gap > ZERO:
            headline = "Liquidity shortfall"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Liquidity projection needs review"
        else:
            headline = "Liquidity within buffer"

        return Analysis(
            headline=headline,
            proposed_decision=(
                "Check buffer limits before action"
                if exceptions
                else "Treasury approver sign-off required"
            ),
            calculations=[
                Calculation("opening_cash", "Opening cash", cash.opening_cash),
                Calculation("expected_inflows", "Expected inflows", cash.expected_inflows),
                Calculation("expected_outflows", "Expected outflows", cash.expected_outflows),
                Calculation("closing_cash", "Projected closing cash", closing),
                Calculation("minimum_liquidity_buffer", "Minimum liquidity buffer", buffer),
                Calculation("funding_gap", "Funding gap", gap),
                Calculation(
                    "forecast_horizon_days",
                    "Forecast horizon (days)",
                    str(cash.forecast_horizon_days),
                    "number",
                ),
            ],
            findings=findings,
            computed={"closing_cash": closing, "funding_gap": gap},
        )
