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
    duplicate_check,
    evidence_check,
    has_severity,
    missing,
    money,
)
from src.app.agent_catalog.agents.financial_close import prompt
from src.app.agent_catalog.agents.financial_close.models import FinancialCloseRun
from src.app.agent_catalog.agents.financial_close.schemas import FinancialCloseInput
from src.app.agent_catalog.runs.models import FlagSeverity


class FinancialCloseAgent(BaseAgent):
    key = "financial_close"
    code = "05"
    name = "Financial Close & Account Reconciliation"
    short_name = "Financial Close"
    description = "Reconcile GL to subledger and draft an exception explanation or journal."
    primary_user = "Controller"
    reviewer = "Controller"

    input_schema = FinancialCloseInput
    run_model = FinancialCloseRun
    reference_field = "gl_account"
    policy_version = "financial_close/v1"
    controls = (
        "Balance mismatch",
        "Materiality",
        "Evidence gaps",
        "Preparer-reviewer separation",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    approval_amount_label = "Absolute variance"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        close = cast(FinancialCloseInput, data)
        return abs(close.gl_balance - close.subledger_balance)

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        close = cast(FinancialCloseInput, data)
        variance = close.gl_balance - close.subledger_balance
        reconciling = close.known_reconciling_items or ZERO
        unexplained = variance - reconciling
        materiality = close.materiality_threshold

        duplicate, duplicate_of = await duplicate_check(
            ctx,
            FinancialCloseRun,
            what="GL account and close period",
            duplicate_code="DUPLICATE_RECONCILIATION",
            clear_code="DUPLICATE_CHECK_CLEAR",
            field="gl_account",
            gl_account=close.gl_account,
            close_period=close.close_period,
        )
        findings: list[Finding] = [duplicate]

        if unexplained == ZERO:
            message = (
                "GL balance agrees to the subledger"
                if variance == ZERO
                else f"Known reconciling items explain the {money(variance)} difference in full"
            )
            findings.append(Finding("BALANCE_MATCH", FlagSeverity.PASS, message, "gl_balance"))
        else:
            explained = (
                f" after {money(reconciling)} of known reconciling items"
                if reconciling != ZERO
                else ""
            )
            findings.append(
                Finding(
                    "BALANCE_MISMATCH",
                    FlagSeverity.WARNING,
                    f"GL {money(close.gl_balance)} vs subledger {money(close.subledger_balance)}: "
                    f"{money(unexplained)} unexplained{explained}",
                    "gl_balance",
                )
            )
            if abs(unexplained) > materiality:
                findings.append(
                    Finding(
                        "MATERIAL_VARIANCE",
                        FlagSeverity.HIGH,
                        f"Unexplained difference {money(unexplained)} exceeds the "
                        f"{money(materiality)} materiality threshold",
                        "materiality_threshold",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "WITHIN_MATERIALITY",
                        FlagSeverity.PASS,
                        f"Unexplained difference is within the {money(materiality)} "
                        "materiality threshold",
                        "materiality_threshold",
                    )
                )
            rationale = missing(
                close.proposed_adjustment_rationale,
                code="MISSING_RATIONALE",
                message="No adjustment rationale for the unexplained difference",
                field="proposed_adjustment_rationale",
            )
            if rationale is not None:
                findings.append(rationale)

        evidence = evidence_check(ctx, "GL detail, subledger report or reconciliation")
        if evidence is not None:
            findings.append(evidence)
        # Enforced by the approval flow itself (a preparer can't approve their own run)
        findings.append(
            Finding(
                "PREPARER_REVIEWER_SEPARATION",
                FlagSeverity.INFO,
                "A different controller must review and approve this reconciliation",
            )
        )

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if duplicate_of is not None:
            headline = "Reconciliation already prepared"
        elif exceptions:
            headline = "Material close variance"
        elif unexplained != ZERO:
            headline = "Immaterial close variance"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Reconciliation needs evidence"
        else:
            headline = "Account reconciled"

        return Analysis(
            headline=headline,
            proposed_decision=(
                "Reconciliation review required" if exceptions else "Controller sign-off required"
            ),
            calculations=[
                Calculation("gl_balance", "GL balance", close.gl_balance),
                Calculation("subledger_balance", "Subledger balance", close.subledger_balance),
                Calculation("variance", "GL - subledger", variance),
                Calculation("known_reconciling_items", "Known reconciling items", reconciling),
                Calculation("unexplained_difference", "Unexplained difference", unexplained),
                Calculation("materiality_threshold", "Materiality threshold", materiality),
            ],
            findings=findings,
            computed={"variance": variance, "unexplained_difference": unexplained},
        )
