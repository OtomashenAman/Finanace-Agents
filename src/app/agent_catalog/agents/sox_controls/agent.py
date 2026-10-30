from datetime import date
from decimal import Decimal
from typing import Any, cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
    Prefill,
)
from src.app.agent_catalog.agents.checks import has_severity, missing, money, percent, ratio_pct
from src.app.agent_catalog.agents.fields import PolicySettings
from src.app.agent_catalog.agents.periods import months_of, period_options
from src.app.agent_catalog.agents.sox_controls import prompt
from src.app.agent_catalog.agents.sox_controls.models import SoxControlsRun
from src.app.agent_catalog.agents.sox_controls.schemas import (
    SoxControlsInput,
    SoxControlsPolicy,
    SoxPrefillParams,
)
from src.app.agent_catalog.runs.models import FlagSeverity
from src.app.data_sources.access import FinanceData
from src.app.data_sources.records import BillPayment, RecordType


def _items(n: int) -> str:
    return f"{n} item{'' if n == 1 else 's'}"


class SoxControlsAgent(BaseAgent):
    key = "sox_controls"
    code = "11"
    name = "Audit Evidence, Controls Testing & SOX"
    short_name = "SOX Controls"
    description = "Test control evidence and produce a traceable exception workpaper."
    primary_user = "Internal Auditor"
    reviewer = "SOX Reviewer"

    input_schema = SoxControlsInput
    run_model = SoxControlsRun
    reference_field = "control_id"
    policy_version = "sox_controls/v1"
    controls = (
        "Sample bounds",
        "Exception count",
        "Evidence lineage",
        "Auditor sign-off",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    policy_schema = SoxControlsPolicy
    prefill_params = SoxPrefillParams

    @classmethod
    async def prefill_options(cls, data: FinanceData) -> dict[str, list[str]]:
        payments = await data.records(BillPayment, RecordType.BILL_PAYMENT)
        months = {f"{p.payment_date:%Y-%m}" for p in payments if p.payment_date}
        return {"test_period": period_options(months)}

    @classmethod
    async def autofill_params(
        cls, values: dict[str, Any], data: FinanceData
    ) -> dict[str, Any] | None:
        if not values.get("test_period") or not await data.has(RecordType.BILL_PAYMENT):
            return None
        threshold = values.get("population_threshold")
        return {
            "test_period": values["test_period"],
            "population_threshold": threshold if threshold is not None else 0,
        }

    @classmethod
    async def prefill_from_data(
        cls, params: BaseModel, data: FinanceData, policy: PolicySettings | None = None
    ) -> Prefill:
        """The supplier payments in the period at or above the threshold: the complete,
        deduplicated population, frozen with the run (count, filters and each payment)."""
        wanted = cast(SoxPrefillParams, params)
        months = set(months_of(wanted.test_period) or [])
        unique = {
            p.external_id: p
            for p in await data.records(BillPayment, RecordType.BILL_PAYMENT)
            if p.payment_date
            and f"{p.payment_date:%Y-%m}" in months
            and p.total >= wanted.population_threshold
        }
        population = sorted(unique.values(), key=lambda p: p.payment_date or date.min)
        threshold = wanted.population_threshold
        values: dict[str, object] = {
            "test_period": wanted.test_period,
            "population_threshold": threshold,
        }
        if population:
            values["population_count"] = len(population)
        return Prefill(
            values,
            reference=f"Supplier payments {wanted.test_period}"
            + (f" of at least {money(threshold)}" if threshold else ""),
            summary={
                "population": "Supplier payments (QuickBooks BillPayment)",
                "period": wanted.test_period,
                "threshold": threshold,
                "count": len(population),
                "total": sum((p.total for p in population), Decimal("0.00")),
                "approval_evidence": "Not in QuickBooks: take approvals from the approval "
                "system; missing evidence is not proof the control failed",
            },
            lines={"population": population},
        )

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        test = cast(SoxControlsInput, data)
        policy = cast(SoxControlsPolicy, ctx.policy) if ctx.policy else SoxControlsPolicy()
        rate = ratio_pct(test.exceptions_found, test.items_tested)
        coverage = ratio_pct(test.items_tested, test.population_count)
        findings: list[Finding] = []

        bounds_ok = True
        if test.items_tested > test.population_count:
            bounds_ok = False
            findings.append(
                Finding(
                    "SAMPLE_EXCEEDS_POPULATION",
                    FlagSeverity.HIGH,
                    f"{_items(test.items_tested)} tested but the population is only "
                    f"{test.population_count}",
                    "items_tested",
                )
            )
        if test.exceptions_found > test.items_tested:
            bounds_ok = False
            findings.append(
                Finding(
                    "EXCEPTIONS_EXCEED_SAMPLE",
                    FlagSeverity.HIGH,
                    f"{test.exceptions_found} exceptions reported from only "
                    f"{_items(test.items_tested)} tested",
                    "exceptions_found",
                )
            )
        minimum = policy.minimum_sample_size
        if (
            bounds_ok
            and minimum is not None
            and test.items_tested < min(minimum, test.population_count)
        ):
            bounds_ok = False
            findings.append(
                Finding(
                    "SAMPLE_TOO_SMALL",
                    FlagSeverity.WARNING,
                    f"Only {_items(test.items_tested)} tested; the minimum sample is {minimum}",
                    "items_tested",
                )
            )
        if bounds_ok:
            findings.append(
                Finding(
                    "SAMPLE_WITHIN_BOUNDS",
                    FlagSeverity.PASS,
                    f"{_items(test.items_tested)} tested from a population of "
                    f"{test.population_count}",
                    "items_tested",
                )
            )

        tolerable = policy.tolerable_exceptions
        if test.exceptions_found == 0:
            findings.append(
                Finding(
                    "NO_EXCEPTIONS",
                    FlagSeverity.PASS,
                    "No exceptions found in the sample",
                    "exceptions_found",
                )
            )
        elif tolerable is not None and test.exceptions_found > tolerable:
            rate_text = f" ({percent(rate)} exception rate)" if rate is not None else ""
            findings.append(
                Finding(
                    "EXCEPTIONS_ABOVE_TOLERABLE",
                    FlagSeverity.HIGH,
                    f"{test.exceptions_found} exceptions in {_items(test.items_tested)} tested"
                    f"{rate_text}, above the {tolerable} tolerable: potential control deficiency",
                    "exceptions_found",
                )
            )
        else:
            findings.append(
                Finding(
                    "EXCEPTIONS_TOLERABLE",
                    FlagSeverity.WARNING,
                    f"{test.exceptions_found} exceptions found, within the tolerable count: "
                    "document each one",
                    "exceptions_found",
                )
            )

        if test.evidence_references or ctx.document_count:
            findings.append(
                Finding(
                    "EVIDENCE_LINEAGE",
                    FlagSeverity.PASS,
                    "Evidence is referenced or attached for the tested items",
                    "evidence_references",
                )
            )
        else:
            findings.append(
                Finding(
                    "MISSING_EVIDENCE_LINEAGE",
                    FlagSeverity.WARNING,
                    "No evidence references or documents: the workpaper can't be traced",
                    "evidence_references",
                )
            )
        procedure = missing(
            test.test_procedure,
            code="MISSING_TEST_PROCEDURE",
            message="No test procedure or expected control described",
            field="test_procedure",
        )
        if procedure is not None:
            findings.append(procedure)
        findings.append(
            Finding(
                "AUDITOR_SIGN_OFF",
                FlagSeverity.INFO,
                "The SOX reviewer signs off the conclusion and any deficiency evaluation",
            )
        )

        exceptions = has_severity(findings, FlagSeverity.HIGH)
        if test.exceptions_found and tolerable is not None and test.exceptions_found > tolerable:
            headline = "Control exceptions found"
        elif exceptions:
            headline = "Sample bounds invalid"
        elif has_severity(findings, FlagSeverity.WARNING):
            headline = "Control test needs completion"
        else:
            headline = "Control operating effectively"

        return Analysis(
            headline=headline,
            proposed_decision=(
                "Auditor validates impact" if exceptions else "SOX reviewer sign-off required"
            ),
            calculations=[
                Calculation(
                    "population_count", "Population count", str(test.population_count), "number"
                ),
                Calculation("items_tested", "Items tested", str(test.items_tested), "number"),
                Calculation(
                    "exceptions_found", "Exceptions found", str(test.exceptions_found), "number"
                ),
                Calculation("exception_rate_pct", "Observed exception rate", rate, "percent"),
                Calculation("sample_coverage_pct", "Sample coverage", coverage, "percent"),
            ],
            findings=findings,
            computed={"exception_rate_pct": rate, "sample_coverage_pct": coverage},
        )
