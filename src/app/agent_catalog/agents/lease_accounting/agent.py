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
    percent,
)
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.agents.lease_accounting import prompt
from src.app.agent_catalog.agents.lease_accounting.models import LeaseAccountingRun
from src.app.agent_catalog.agents.lease_accounting.schemas import (
    LeaseAccountingInput,
    LeaseAccountingPolicy,
)
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.models import DataSource
from src.app.data_sources.records import CENT, Bill, Record, RecordType


def lease_liability(payment: Decimal, months: int, annual_rate_pct: Decimal) -> Decimal:
    """Present value of `months` equal payments made at the end of each month."""
    rate = annual_rate_pct / 1200
    if rate == 0:
        return (payment * months).quantize(CENT)
    factor = (1 - (1 + rate) ** -months) / rate
    return (payment * factor).quantize(CENT, ROUND_HALF_UP)


def _liability(lease: LeaseAccountingInput) -> Decimal:
    return lease_liability(
        lease.monthly_payment, lease.remaining_term_months, lease.annual_discount_rate
    )


def _months(n: int) -> str:
    return f"{n} month{'' if n == 1 else 's'}"


class LeaseAccountingAgent(BaseAgent):
    key = "lease_accounting"
    code = "10"
    name = "Lease Accounting & Contract Abstraction"
    short_name = "Lease Accounting"
    description = "Extract lease terms and build a preliminary amortization illustration."
    primary_user = "Lease Accountant"
    reviewer = "Lease Accounting Reviewer"

    input_schema = LeaseAccountingInput
    run_model = LeaseAccountingRun
    reference_field = "leased_asset"
    policy_version = "lease_accounting/v1"
    controls = (
        "Lease classification",
        "Discount rate",
        "Renewal/termination options",
        "Lease modifications",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    # A rent bill: QuickBooks has no lease object, but the lessor bills the payment
    source_record_type = RecordType.BILL
    policy_schema = LeaseAccountingPolicy
    approval_amount_label = "Lease liability"

    @classmethod
    async def prefill(
        cls,
        record: Record,
        source: DataSource,
        data: FinanceData,
        policy: PolicySettings | None = None,
    ) -> Prefill:
        bill = cast(Bill, record)
        values: dict[str, object] = {"lessor": bill.vendor_name}
        if bill.total > ZERO:
            values["monthly_payment"] = bill.total
        # Term, rate and options come from the lease agreement, not the books
        return Prefill(values)

    @staticmethod
    async def _ledger_checks(lease: LeaseAccountingInput, ctx: AnalysisContext) -> list[Finding]:
        """Against the lessor's bills in the preparer's data source, if they have bills."""
        if not await ctx.data.has(RecordType.BILL):
            return []
        bills = await ctx.data.records(Bill, RecordType.BILL, counterparty=lease.lessor)
        if not bills:
            return [
                Finding(
                    "NO_LESSOR_BILLS",
                    FlagSeverity.WARNING,
                    f"No bills from {lease.lessor} in your data source: confirm the payments",
                    "lessor",
                )
            ]
        latest = max(bills, key=lambda b: b.bill_date or date.min)
        if latest.total != lease.monthly_payment:
            return [
                Finding(
                    "PAYMENT_DIFFERS_FROM_BILLS",
                    FlagSeverity.WARNING,
                    f"The latest bill from {lease.lessor} ({latest.doc_number}) is "
                    f"{money(latest.total)}, not the {money(lease.monthly_payment)} monthly "
                    "payment: check for escalations or non-lease charges",
                    "monthly_payment",
                )
            ]
        return [
            Finding(
                "PAYMENT_MATCHES_BILLS",
                FlagSeverity.PASS,
                f"The monthly payment matches the latest bill from {lease.lessor} "
                f"({latest.doc_number})",
                "monthly_payment",
            )
        ]

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return _liability(cast(LeaseAccountingInput, data))

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        lease = cast(LeaseAccountingInput, data)
        policy = cast(LeaseAccountingPolicy, ctx.policy) if ctx.policy else LeaseAccountingPolicy()
        months = lease.remaining_term_months
        rate = lease.annual_discount_rate
        liability = _liability(lease)
        rou_asset = liability + (lease.initial_direct_costs or ZERO)
        total_payments = lease.monthly_payment * months
        interest = total_payments - liability
        findings: list[Finding] = []

        short_term = policy.short_term_months
        if short_term is not None and months <= short_term:
            findings.append(
                Finding(
                    "SHORT_TERM_LEASE",
                    FlagSeverity.INFO,
                    f"{_months(months)} remaining: the short-term exemption may apply if there "
                    "is no purchase option reasonably certain to be exercised",
                    "remaining_term_months",
                )
            )
        else:
            findings.append(
                Finding(
                    "LEASE_CLASSIFICATION",
                    FlagSeverity.INFO,
                    "The reviewer classifies the lease (finance or operating): ownership "
                    "transfer, purchase option, term vs economic life, PV vs fair value",
                    "leased_asset",
                )
            )

        low, high = policy.minimum_discount_rate, policy.maximum_discount_rate
        if rate == ZERO:
            findings.append(
                Finding(
                    "NO_DISCOUNT_RATE",
                    FlagSeverity.HIGH,
                    "Discount rate is 0%: the liability equals the undiscounted payments",
                    "annual_discount_rate",
                )
            )
        elif (low is not None and rate < low) or (high is not None and rate > high):
            findings.append(
                Finding(
                    "DISCOUNT_RATE_OUT_OF_RANGE",
                    FlagSeverity.WARNING,
                    f"Discount rate {percent(rate)} is outside the expected "
                    f"{percent(low or ZERO)} to {percent(high) if high is not None else 'any'} "
                    "range: support the rate used",
                    "annual_discount_rate",
                )
            )
        else:
            findings.append(
                Finding(
                    "DISCOUNT_RATE_IN_RANGE",
                    FlagSeverity.PASS,
                    f"Discount rate {percent(rate)} annual is within the expected range",
                    "annual_discount_rate",
                )
            )

        if lease.renewal_termination_options:
            findings.append(
                Finding(
                    "RENEWAL_TERMINATION_OPTIONS",
                    FlagSeverity.WARNING,
                    f"Renewal or termination options described: the {_months(months)} term "
                    "must include periods reasonably certain to be exercised",
                    "renewal_termination_options",
                )
            )
        else:
            findings.append(
                Finding(
                    "NO_OPTIONS_RECORDED",
                    FlagSeverity.WARNING,
                    "No renewal or termination options recorded: confirm the lease has none",
                    "renewal_termination_options",
                )
            )

        analyzed_before = await earlier_run(
            ctx, LeaseAccountingRun, lessor=lease.lessor, leased_asset=lease.leased_asset
        )
        if analyzed_before is not None:
            findings.append(
                Finding(
                    "LEASE_MODIFICATION",
                    FlagSeverity.WARNING,
                    f"This lease was already analyzed in RUN-{analyzed_before:05d}: if its "
                    "terms changed, account for it as a lease modification",
                    "leased_asset",
                )
            )
        else:
            findings.append(
                Finding(
                    "NO_EARLIER_RUN",
                    FlagSeverity.PASS,
                    "No earlier run for this lessor and asset",
                    "leased_asset",
                )
            )

        findings.extend(await cls._ledger_checks(lease, ctx))
        optional_checks = [
            missing(
                lease.lease_clauses,
                code="MISSING_LEASE_CLAUSES",
                message="No lease clauses entered: the clause review has nothing to cite",
                field="lease_clauses",
            ),
            evidence_check(ctx, "signed lease agreement"),
        ]
        findings.extend(f for f in optional_checks if f is not None)

        if has_severity(findings, FlagSeverity.HIGH):
            headline = "Lease assumptions incomplete"
        elif short_term is not None and months <= short_term:
            headline = "Short-term lease"
        else:
            headline = "Lease schedule"

        needs_review = has_severity(findings, FlagSeverity.HIGH) or has_severity(
            findings, FlagSeverity.WARNING
        )
        return Analysis(
            headline=headline,
            proposed_decision=(
                "Classification and assumptions need review"
                if needs_review
                else "Lease accounting reviewer sign-off required"
            ),
            calculations=[
                Calculation("monthly_payment", "Monthly payment", lease.monthly_payment),
                Calculation(
                    "remaining_term_months", "Remaining term (months)", str(months), "number"
                ),
                Calculation("annual_discount_rate", "Annual discount rate", rate, "percent"),
                Calculation("total_payments", "Total remaining payments", total_payments),
                Calculation(
                    "lease_liability", "Indicative lease liability (PV, end of month)", liability
                ),
                Calculation(
                    "initial_direct_costs",
                    "Initial direct costs",
                    lease.initial_direct_costs or ZERO,
                ),
                Calculation("right_of_use_asset", "Indicative right-of-use asset", rou_asset),
                Calculation("total_interest", "Total interest over the term", interest),
            ],
            findings=findings,
            computed={
                "lease_liability": liability,
                "right_of_use_asset": rou_asset,
                "total_interest": interest,
            },
        )
