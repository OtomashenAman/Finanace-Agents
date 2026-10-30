import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
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
    earlier_run,
    evidence_check,
    has_severity,
    missing,
    money,
    over_limit,
)
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.agents.revenue_recognition import prompt
from src.app.agent_catalog.agents.revenue_recognition.models import RevenueRecognitionRun
from src.app.agent_catalog.agents.revenue_recognition.schemas import (
    RevenueRecognitionInput,
    RevenueRecognitionPolicy,
)
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource
from src.app.data_sources.records import CENT, Invoice, Record, RecordType

# "Hosting and support", "Hosting; Support", one per line, ... ("90,000.00" is not split)
_SEPARATORS = re.compile(r"\n|;|,\s|\s+and\s+|\s*[&+]\s*", re.IGNORECASE)
_CHANGE_WORDS = re.compile(
    r"modif|amend|change|renew|extend|extension|terminat|upgrade|downgrade", re.IGNORECASE
)


def obligations(text: str) -> list[str]:
    """The separate performance obligations the preparer listed."""
    parts = (p.strip(" \t-•*") for p in _SEPARATORS.split(text))
    return [p for p in parts if p]


def service_months(start: date | None, end: date | None) -> int | None:
    """Calendar months from the first to the last service date, both included (Jan-Dec: 12)."""
    if start is None or end is None or end < start:
        return None
    return (end.year - start.year) * 12 + end.month - start.month + 1


def _monthly(data: RevenueRecognitionInput) -> Decimal:
    return (data.contract_total / data.service_term_months).quantize(CENT, ROUND_HALF_UP)


def _final_month(data: RevenueRecognitionInput) -> Decimal:
    """The last month takes the rounding, so the months add up to the contract total."""
    return data.contract_total - _monthly(data) * (data.service_term_months - 1)


class RevenueRecognitionAgent(BaseAgent):
    key = "revenue_recognition"
    code = "09"
    name = "Revenue Recognition & Contract Accounting"
    short_name = "Revenue Recognition"
    description = "Abstract ASC 606/IFRS 15 facts and draft a schedule for review."
    primary_user = "Revenue Accountant"
    reviewer = "Revenue Controller"

    input_schema = RevenueRecognitionInput
    run_model = RevenueRecognitionRun
    reference_field = "contract_id"
    policy_version = "revenue_recognition/v1"
    controls = (
        "Distinct obligations",
        "Variable consideration",
        "Contract changes",
        "Policy review",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    source_record_type = RecordType.INVOICE
    policy_schema = RevenueRecognitionPolicy
    approval_amount_label = "Contract total"

    @classmethod
    async def prefill(
        cls,
        record: Record,
        source: DataSource,
        data: FinanceData,
        policy: PolicySettings | None = None,
    ) -> Prefill:
        invoice = cast(Invoice, record)
        values: dict[str, object] = {
            "customer": invoice.customer_name,
            "contract_id": invoice.doc_number,
            "contract_total": invoice.total if invoice.total > ZERO else None,
            "service_term_months": service_months(invoice.service_start, invoice.service_end),
            "performance_obligations": invoice.line_items,
        }
        # Only what the invoice knows: clauses and variable consideration come from the contract
        return Prefill({k: v for k, v in values.items() if v is not None})

    @staticmethod
    async def _ledger_checks(rev: RevenueRecognitionInput, ctx: AnalysisContext) -> list[Finding]:
        """Against the preparer's customer invoices, when the contract ID is an invoice number."""
        if not await ctx.data.has(RecordType.INVOICE):
            return []
        invoice = await ctx.data.find(Invoice, RecordType.INVOICE, rev.contract_id)
        if invoice is None:
            return []
        if invoice.customer_name.lower() != rev.customer.lower():
            return [
                Finding(
                    "INVOICE_CUSTOMER_MISMATCH",
                    FlagSeverity.HIGH,
                    f"Invoice {invoice.doc_number} in your data source is for "
                    f"{invoice.customer_name}, not {rev.customer}",
                    "customer",
                )
            ]
        findings = [
            Finding(
                "CONTRACT_INVOICE_FOUND",
                FlagSeverity.PASS,
                f"Invoice {invoice.doc_number} for {invoice.customer_name} is in your data source",
                "contract_id",
            )
        ]
        if invoice.total != rev.contract_total:
            findings.append(
                Finding(
                    "INVOICED_DIFFERS_FROM_CONTRACT",
                    FlagSeverity.INFO,
                    f"Invoiced {money(invoice.total)} (tax included) vs contract total "
                    f"{money(rev.contract_total)}: billing need not match revenue timing",
                    "contract_total",
                )
            )
        return findings

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return cast(RevenueRecognitionInput, data).contract_total

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        rev = cast(RevenueRecognitionInput, data)
        policy = (
            cast(RevenueRecognitionPolicy, ctx.policy) if ctx.policy else RevenueRecognitionPolicy()
        )
        listed = obligations(rev.performance_obligations)
        monthly = _monthly(rev)
        findings: list[Finding] = []

        if len(listed) > 1:
            findings.append(
                Finding(
                    "MULTIPLE_OBLIGATIONS",
                    FlagSeverity.HIGH,
                    f"{len(listed)} performance obligations listed: allocate the "
                    f"{money(rev.contract_total)} by standalone selling price; the straight-line "
                    "illustration treats the contract as one",
                    "performance_obligations",
                )
            )
        else:
            findings.append(
                Finding(
                    "SINGLE_OBLIGATION",
                    FlagSeverity.PASS,
                    "One performance obligation listed: confirm it is satisfied over the "
                    "service term",
                    "performance_obligations",
                )
            )

        if rev.variable_consideration:
            findings.append(
                Finding(
                    "VARIABLE_CONSIDERATION",
                    FlagSeverity.WARNING,
                    "Variable consideration or modifications described: estimate and constrain "
                    "them before relying on the illustration",
                    "variable_consideration",
                )
            )
            if _CHANGE_WORDS.search(rev.variable_consideration):
                findings.append(
                    Finding(
                        "CONTRACT_CHANGES",
                        FlagSeverity.WARNING,
                        "A contract change is described: assess whether it is a separate "
                        "contract or a modification of this one",
                        "variable_consideration",
                    )
                )
        else:
            findings.append(
                Finding(
                    "FIXED_CONSIDERATION",
                    FlagSeverity.PASS,
                    "No variable consideration or contract changes recorded",
                    "variable_consideration",
                )
            )

        analyzed_before = await earlier_run(ctx, RevenueRecognitionRun, contract_id=rev.contract_id)
        if analyzed_before is not None:
            findings.append(
                Finding(
                    "CONTRACT_ANALYZED_BEFORE",
                    FlagSeverity.WARNING,
                    f"Contract {rev.contract_id} was already analyzed in "
                    f"RUN-{analyzed_before:05d}: if its terms changed, account for the "
                    "modification",
                    "contract_id",
                )
            )

        findings.extend(await cls._ledger_checks(rev, ctx))
        optional_checks = [
            over_limit(
                rev.contract_total,
                policy.policy_review_amount,
                code="POLICY_REVIEW",
                message=(
                    f"Contract total is above the "
                    f"{money(policy.policy_review_amount or ZERO)} revenue policy review limit"
                ),
                field="contract_total",
            ),
            missing(
                rev.contract_clauses,
                code="MISSING_CONTRACT_CLAUSES",
                message="No contract clauses entered: the memo can't cite the contract terms",
                field="contract_clauses",
            ),
            evidence_check(ctx, "signed contract or order form"),
        ]
        findings.extend(f for f in optional_checks if f is not None)
        findings.append(
            Finding(
                "PRELIMINARY_ILLUSTRATION",
                FlagSeverity.INFO,
                "Straight-line illustration only: the revenue controller concludes on the "
                "ASC 606 / IFRS 15 treatment",
            )
        )

        if len(listed) > 1:
            headline = "Allocation across obligations needed"
        elif has_severity(findings, FlagSeverity.HIGH):
            headline = "Contract data mismatch"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Contract needs review"
        else:
            headline = "Single-obligation contract"

        needs_review = has_severity(findings, FlagSeverity.HIGH) or has_severity(
            findings, FlagSeverity.WARNING
        )
        return Analysis(
            headline=headline,
            proposed_decision=(
                "Needs obligation and policy review"
                if needs_review
                else "Revenue controller sign-off required"
            ),
            calculations=[
                Calculation("contract_total", "Contract total", rev.contract_total),
                Calculation(
                    "service_term_months",
                    "Service term (months)",
                    str(rev.service_term_months),
                    "number",
                ),
                Calculation(
                    "obligation_count", "Performance obligations listed", str(len(listed)), "number"
                ),
                Calculation(
                    "monthly_revenue", "Illustrative monthly revenue (straight-line)", monthly
                ),
                Calculation(
                    "final_month_revenue", "Final month (takes rounding)", _final_month(rev)
                ),
            ],
            findings=findings,
            computed={"monthly_revenue": monthly, "obligation_count": len(listed)},
        )
