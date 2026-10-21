import re
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
    money,
    tolerance_check,
)
from src.app.agent_catalog.agents.expense_audit import prompt
from src.app.agent_catalog.agents.expense_audit.models import ExpenseAuditRun
from src.app.agent_catalog.agents.expense_audit.schemas import (
    ExpenseAuditInput,
    ExpenseAuditPolicy,
)
from src.app.agent_catalog.runs.models import FlagSeverity

_ID_SEPARATORS = re.compile(r"[\s,;]+")


def _prior_ids(text: str | None) -> set[str]:
    return {i.lower() for i in _ID_SEPARATORS.split(text or "") if i}


class ExpenseAuditAgent(BaseAgent):
    key = "expense_audit"
    code = "02"
    name = "Expense Audit & Corporate Card Compliance"
    short_name = "Expense Audit"
    description = "Evaluate receipts and card claims for duplicate, policy and anomaly risk."
    primary_user = "Expense Auditor"
    reviewer = "Finance Audit"

    input_schema = ExpenseAuditInput
    run_model = ExpenseAuditRun
    reference_field = "employee"
    policy_version = "expense_audit/v1"
    controls = (
        "Receipt completeness",
        "Policy limit",
        "Amount reconciliation",
        "Duplicate card transaction",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    draft_message = "Clarification request to the employee about this expense claim"
    policy_schema = ExpenseAuditPolicy
    approval_amount_label = "Claim amount"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return cast(ExpenseAuditInput, data).claim_amount

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        claim = cast(ExpenseAuditInput, data)
        policy = cast(ExpenseAuditPolicy, ctx.policy) if ctx.policy else ExpenseAuditPolicy()
        over_limit = claim.claim_amount - claim.policy_limit
        findings: list[Finding] = []

        duplicate = False
        if claim.card_transaction_id:
            if claim.card_transaction_id.lower() in _prior_ids(claim.prior_card_transaction_ids):
                duplicate = True
                findings.append(
                    Finding(
                        "DUPLICATE_CARD_TRANSACTION",
                        FlagSeverity.HIGH,
                        f"Card transaction {claim.card_transaction_id} is already in the prior "
                        "card transaction IDs",
                        "card_transaction_id",
                    )
                )
            else:
                finding, earlier = await duplicate_check(
                    ctx,
                    ExpenseAuditRun,
                    what="card transaction ID",
                    duplicate_code="DUPLICATE_CARD_TRANSACTION",
                    clear_code="DUPLICATE_CHECK_CLEAR",
                    field="card_transaction_id",
                    card_transaction_id=claim.card_transaction_id,
                )
                duplicate = earlier is not None
                findings.append(finding)

        if claim.receipt_provided:
            findings.append(
                Finding(
                    "RECEIPT_PROVIDED", FlagSeverity.PASS, "Receipt provided", "receipt_provided"
                )
            )
        else:
            findings.append(
                Finding(
                    "MISSING_RECEIPT",
                    FlagSeverity.HIGH,
                    "No receipt provided for the claim",
                    "receipt_provided",
                )
            )

        if over_limit > ZERO:
            findings.append(
                Finding(
                    "POLICY_LIMIT_EXCEEDED",
                    FlagSeverity.HIGH,
                    f"Claim {money(claim.claim_amount)} exceeds the {money(claim.policy_limit)} "
                    f"policy limit by {money(over_limit)}",
                    "policy_limit",
                )
            )
        else:
            findings.append(
                Finding(
                    "WITHIN_POLICY_LIMIT",
                    FlagSeverity.PASS,
                    f"Claim is within the {money(claim.policy_limit)} policy limit",
                    "policy_limit",
                )
            )

        claim_vs_receipt = None
        if claim.receipt_total is not None:
            claim_vs_receipt = claim.claim_amount - claim.receipt_total
            findings.append(
                tolerance_check(
                    claim_vs_receipt,
                    policy.receipt_tolerance,
                    subject="Claim amount",
                    other="the receipt total",
                    tolerance_name="receipt",
                    match_code="AMOUNT_RECONCILED",
                    mismatch_code="AMOUNT_MISMATCH",
                    field="receipt_total",
                )
            )
        elif claim.receipt_provided:
            findings.append(
                Finding(
                    "MISSING_RECEIPT_TOTAL",
                    FlagSeverity.WARNING,
                    "Receipt provided but its total wasn't entered: the claim can't be reconciled",
                    "receipt_total",
                )
            )

        evidence = evidence_check(ctx, "receipt or card statement")
        if evidence is not None:
            findings.append(evidence)

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if duplicate:
            headline = "Duplicate card transaction"
        elif over_limit > ZERO:
            headline = "Policy exception"
        elif exceptions:
            headline = "Expense exception"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Expense needs completion"
        else:
            headline = "Expense within policy"

        calculations = [
            Calculation("claim_amount", "Claim amount", claim.claim_amount),
            Calculation("policy_limit", "Policy limit", claim.policy_limit),
            Calculation("over_limit_amount", "Over policy limit", max(over_limit, ZERO)),
        ]
        if claim.receipt_total is not None:
            calculations += [
                Calculation("receipt_total", "Receipt total", claim.receipt_total),
                Calculation("claim_vs_receipt", "Claim - receipt", claim_vs_receipt),
            ]
        return Analysis(
            headline=headline,
            proposed_decision=(
                "Request explanation or reject" if exceptions else "Finance audit approval required"
            ),
            calculations=calculations,
            findings=findings,
            computed={
                "over_limit_amount": max(over_limit, ZERO),
                "claim_vs_receipt": claim_vs_receipt,
            },
        )
