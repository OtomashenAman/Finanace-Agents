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
from src.app.agent_catalog.agents.cash_application import prompt
from src.app.agent_catalog.agents.cash_application.models import CashApplicationRun
from src.app.agent_catalog.agents.cash_application.schemas import (
    CashApplicationInput,
    CashApplicationPolicy,
)
from src.app.agent_catalog.agents.checks import (
    ZERO,
    duplicate_check,
    evidence_check,
    has_severity,
    missing,
    money,
)
from src.app.agent_catalog.runs.models import FlagSeverity


class CashApplicationAgent(BaseAgent):
    key = "cash_application"
    code = "04"
    name = "Cash Application & Deductions Resolution"
    short_name = "Cash Application"
    description = "Match bank remittances to open invoices and identify deductions."
    primary_user = "Cash Analyst"
    reviewer = "Cash Application Reviewer"

    input_schema = CashApplicationInput
    run_model = CashApplicationRun
    reference_field = "payment_reference"
    policy_version = "cash_application/v1"
    controls = (
        "Invoice reference match",
        "Amount difference",
        "Deduction threshold",
        "Ambiguous remittance",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    policy_schema = CashApplicationPolicy
    approval_amount_label = "Payment amount"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return cast(CashApplicationInput, data).payment_amount

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        cash = cast(CashApplicationInput, data)
        policy = cast(CashApplicationPolicy, ctx.policy) if ctx.policy else CashApplicationPolicy()
        short = cash.invoice_open_amount - cash.payment_amount  # negative: overpaid
        matched = abs(short) <= policy.match_tolerance

        duplicate, duplicate_of = await duplicate_check(
            ctx,
            CashApplicationRun,
            what="payment reference",
            duplicate_code="DUPLICATE_PAYMENT",
            clear_code="DUPLICATE_CHECK_CLEAR",
            field="payment_reference",
            payment_reference=cash.payment_reference,
        )
        findings: list[Finding] = [duplicate]

        if cash.reference_verified:
            findings.append(
                Finding(
                    "INVOICE_REFERENCE_MATCH",
                    FlagSeverity.PASS,
                    f"Payment reference verified against invoice {cash.candidate_invoice_number}",
                    "reference_verified",
                )
            )
        else:
            findings.append(
                Finding(
                    "REFERENCE_NOT_VERIFIED",
                    FlagSeverity.WARNING,
                    f"Payment reference not verified against invoice "
                    f"{cash.candidate_invoice_number}",
                    "reference_verified",
                )
            )

        if short == ZERO:
            findings.append(
                Finding(
                    "AMOUNT_MATCH",
                    FlagSeverity.PASS,
                    "Payment matches the invoice open amount",
                    "payment_amount",
                )
            )
        elif matched:
            findings.append(
                Finding(
                    "AMOUNT_MATCH",
                    FlagSeverity.PASS,
                    f"Payment is within the {money(policy.match_tolerance)} match tolerance "
                    f"(difference {money(short)})",
                    "payment_amount",
                )
            )
        elif short > ZERO:
            findings.append(
                Finding(
                    "SHORT_PAYMENT",
                    FlagSeverity.WARNING,
                    f"Payment is {money(short)} short of the invoice open amount "
                    f"{money(cash.invoice_open_amount)}",
                    "payment_amount",
                )
            )
            threshold = policy.deduction_review_amount
            if threshold is not None and short > threshold:
                findings.append(
                    Finding(
                        "DEDUCTION_REVIEW",
                        FlagSeverity.HIGH,
                        f"Deduction of {money(short)} requires classification (above the "
                        f"{money(threshold)} review threshold)",
                        "payment_amount",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "DEDUCTION_BELOW_THRESHOLD",
                        FlagSeverity.INFO,
                        f"Short payment of {money(short)} is within the deduction review threshold",
                        "payment_amount",
                    )
                )
        else:
            findings.append(
                Finding(
                    "OVERPAYMENT",
                    FlagSeverity.WARNING,
                    f"Payment exceeds the invoice open amount by {money(-short)}: unapplied "
                    "cash or a refund to resolve",
                    "payment_amount",
                )
            )

        if not matched:
            remittance = missing(
                cash.remittance_advice,
                code="AMBIGUOUS_REMITTANCE",
                message="No remittance advice: the reason for the difference can't be confirmed",
                field="remittance_advice",
            )
            if remittance is not None:
                findings.append(remittance)
        evidence = evidence_check(ctx, "bank receipt or remittance advice")
        if evidence is not None:
            findings.append(evidence)

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if duplicate_of is not None:
            headline = "Payment already applied"
        elif short > ZERO and not matched:
            headline = "Short payment"
        elif short < ZERO and not matched:
            headline = "Overpayment"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Cash match candidate"
        else:
            headline = "Payment matches invoice"

        if any(f.code == "DEDUCTION_REVIEW" for f in findings):
            decision = "Deduction requires classification"
        elif exceptions:
            decision = "Resolve exceptions before applying cash"
        else:
            decision = "Cash application reviewer approval required"
        return Analysis(
            headline=headline,
            proposed_decision=decision,
            calculations=[
                Calculation("payment_amount", "Payment amount", cash.payment_amount),
                Calculation("invoice_open_amount", "Invoice open amount", cash.invoice_open_amount),
                Calculation("short_payment", "Invoice open - payment", short),
            ],
            findings=findings,
            computed={"short_payment": short},
        )
