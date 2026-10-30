from typing import cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
)
from src.app.agent_catalog.agents.checks import has_severity, missing, percent, ratio_pct
from src.app.agent_catalog.agents.sox_controls import prompt
from src.app.agent_catalog.agents.sox_controls.models import SoxControlsRun
from src.app.agent_catalog.agents.sox_controls.schemas import SoxControlsInput, SoxControlsPolicy
from src.app.agent_catalog.runs.models import FlagSeverity


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
