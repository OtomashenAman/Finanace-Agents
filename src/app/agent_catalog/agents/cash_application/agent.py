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
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource
from src.app.data_sources.records import Invoice, Payment, Record, RecordType


def _mentions(text: str, number: str) -> bool:
    """Whether `number` appears as a whole reference (INV-1 is not in INV-10)."""
    return re.search(rf"(?<![\w-]){re.escape(number)}(?![\w-])", text, re.IGNORECASE) is not None


async def candidate_invoice(payment: Payment, data: FinanceData) -> tuple[Invoice | None, bool]:
    """The invoice this payment is most likely for, and whether that is verified.

    In order: the invoice it is applied to in the source (verified); the one open invoice of
    the customer its reference or memo names (verified); the one open invoice of the customer
    for exactly this amount (not verified). Otherwise none: the preparer picks.
    """
    if payment.invoice_number:
        linked = await data.find(Invoice, RecordType.INVOICE, payment.invoice_number)
        if linked is not None:
            return linked, True
    invoices = await data.records(Invoice, RecordType.INVOICE, counterparty=payment.customer_name)
    open_invoices = [i for i in invoices if i.open_amount > ZERO]
    text = f"{payment.reference_number} {payment.memo or ''}"
    named = [i for i in open_invoices if _mentions(text, i.doc_number)]
    if len(named) == 1:
        return named[0], True
    same_amount = [i for i in open_invoices if i.open_amount == payment.total]
    if len(same_amount) == 1:
        return same_amount[0], False
    return None, False


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
    source_record_type = RecordType.PAYMENT
    policy_schema = CashApplicationPolicy
    approval_amount_label = "Payment amount"

    @classmethod
    async def prefill(
        cls,
        record: Record,
        source: DataSource,
        data: FinanceData,
        policy: PolicySettings | None = None,
    ) -> Prefill:
        payment = cast(Payment, record)
        values: dict[str, object] = {
            "customer": payment.customer_name,
            "payment_reference": payment.reference_number,
            "payment_amount": payment.total if payment.total > ZERO else None,
            "remittance_advice": payment.memo,
        }
        invoice, verified = await candidate_invoice(payment, data)
        related: dict[str, Record] = {}
        if invoice is not None:
            related["invoice"] = invoice
            open_amount = invoice.open_amount
            if invoice.doc_number == payment.invoice_number:
                # Already applied in the source: its balance is net of this payment
                open_amount += payment.applied_amount or ZERO
            values["candidate_invoice_number"] = invoice.doc_number
            values["invoice_open_amount"] = open_amount if open_amount > ZERO else None
            values["reference_verified"] = verified
        else:
            values["candidate_invoice_number"] = payment.invoice_number
        # Only what the source knows: the preparer completes the rest
        return Prefill({k: v for k, v in values.items() if v is not None}, related)

    @staticmethod
    async def _ledger_checks(cash: CashApplicationInput, ctx: AnalysisContext) -> list[Finding]:
        """Against the preparer's customer invoices (QuickBooks or an upload), if they have them."""
        if not await ctx.data.has(RecordType.INVOICE):
            return []
        number = cash.candidate_invoice_number
        invoice = await ctx.data.find(Invoice, RecordType.INVOICE, number)
        if invoice is None:
            return [
                Finding(
                    "INVOICE_NOT_FOUND",
                    FlagSeverity.WARNING,
                    f"Invoice {number} isn't in your data source",
                    "candidate_invoice_number",
                )
            ]
        if invoice.customer_name.lower() != cash.customer.lower():
            return [
                Finding(
                    "INVOICE_CUSTOMER_MISMATCH",
                    FlagSeverity.HIGH,
                    f"Invoice {number} belongs to {invoice.customer_name}, not {cash.customer}",
                    "candidate_invoice_number",
                )
            ]
        return [
            Finding(
                "INVOICE_IN_LEDGER",
                FlagSeverity.PASS,
                f"Invoice {number} is in your data source for {invoice.customer_name}",
                "candidate_invoice_number",
            )
        ]

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

        findings.extend(await cls._ledger_checks(cash, ctx))

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
