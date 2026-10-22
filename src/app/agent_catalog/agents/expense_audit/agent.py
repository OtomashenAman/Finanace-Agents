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
    Prefill,
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
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource
from src.app.data_sources.records import Expense, Record, RecordType

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
    source_record_type = RecordType.EXPENSE
    policy_schema = ExpenseAuditPolicy
    approval_amount_label = "Claim amount"

    @classmethod
    async def prefill(
        cls,
        record: Record,
        source: DataSource,
        data: FinanceData,
        policy: PolicySettings | None = None,
    ) -> Prefill:
        expense = cast(Expense, record)
        limits = cast(ExpenseAuditPolicy, policy) if policy else ExpenseAuditPolicy()
        values = {
            "employee": expense.employee,
            "merchant": expense.vendor_name,
            "claim_amount": expense.total if expense.total > ZERO else None,
            "policy_limit": limits.limit_for(expense.account),
            "receipt_provided": expense.has_receipt,
            "card_transaction_id": expense.transaction_id,
        }
        # Only what the source knows: the preparer completes the rest (e.g. the receipt total)
        return Prefill({k: v for k, v in values.items() if v is not None})

    @staticmethod
    async def _card_checks(claim: ExpenseAuditInput, ctx: AnalysisContext) -> list[Finding]:
        """Against the preparer's card transactions (QuickBooks or an upload), if they have them."""
        if not claim.card_transaction_id or not await ctx.data.has(RecordType.EXPENSE):
            return []
        charge = await ctx.data.find(Expense, RecordType.EXPENSE, claim.card_transaction_id)
        if charge is None:
            return [
                Finding(
                    "CARD_TRANSACTION_NOT_FOUND",
                    FlagSeverity.WARNING,
                    f"Card transaction {claim.card_transaction_id} isn't in your data source",
                    "card_transaction_id",
                )
            ]
        findings = []
        if charge.total != claim.claim_amount:
            findings.append(
                Finding(
                    "CLAIM_DIFFERS_FROM_CHARGE",
                    FlagSeverity.WARNING,
                    f"Claim {money(claim.claim_amount)} differs from the card transaction amount "
                    f"{money(charge.total)}",
                    "claim_amount",
                )
            )
        same_merchant = await ctx.data.records(
            Expense, RecordType.EXPENSE, counterparty=charge.vendor_name
        )
        twins = [
            e.transaction_id
            for e in same_merchant
            if e.transaction_id != charge.transaction_id
            and e.total == charge.total
            and e.expense_date == charge.expense_date
        ]
        if twins:
            findings.append(
                Finding(
                    "DUPLICATE_CHARGE",
                    FlagSeverity.HIGH,
                    f"Same merchant, amount and date as card transaction {', '.join(twins)}",
                    "card_transaction_id",
                )
            )
        return findings

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
        card_findings = await cls._card_checks(claim, ctx)
        duplicate = duplicate or any(f.code == "DUPLICATE_CHARGE" for f in card_findings)
        findings.extend(card_findings)

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
