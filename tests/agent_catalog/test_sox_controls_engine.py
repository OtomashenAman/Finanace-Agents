from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.sox_controls import SoxControlsAgent
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import codes, run_analysis

# Values from the requirement deck's SOX example
PDF_EXAMPLE = {
    "control_id": "SOX-AP-003",
    "control_owner": "AP Controller",
    "population_count": "100",
    "items_tested": "25",
    "exceptions_found": "2",
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, int] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, SoxControlsAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_has_an_8_percent_exception_rate(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Control exceptions found"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Auditor validates impact"
    assert codes(analysis) == {
        "SAMPLE_WITHIN_BOUNDS": "pass",
        "EXCEPTIONS_ABOVE_TOLERABLE": "high",
        "MISSING_EVIDENCE_LINEAGE": "warning",
        "MISSING_TEST_PROCEDURE": "warning",
        "AUDITOR_SIGN_OFF": "info",
    }
    above = next(f for f in analysis.findings if f.code == "EXCEPTIONS_ABOVE_TOLERABLE")
    assert above.message == (
        "2 exceptions in 25 items tested (8% exception rate), above the 0 tolerable: "
        "potential control deficiency"
    )
    assert analysis.computed == {
        "exception_rate_pct": Decimal("8.00"),
        "sample_coverage_pct": Decimal("25.00"),
    }


async def test_clean_test_with_evidence(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        exceptions_found="0",
        evidence_references="SharePoint /SOX/AP-003/2026-Q3",
        test_procedure="Reperform three-way match",
    )

    assert analysis.headline == "Control operating effectively"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "SOX reviewer sign-off required"
    assert {s for c, s in codes(analysis).items() if c != "AUDITOR_SIGN_OFF"} == {"pass"}


async def test_invalid_sample_bounds(db: AsyncSession) -> None:
    analysis = await analyze(db, population_count="20", items_tested="25", exceptions_found="30")

    found = codes(analysis)
    assert analysis.headline == "Control exceptions found"
    assert found["SAMPLE_EXCEEDS_POPULATION"] == "high"
    assert found["EXCEPTIONS_EXCEED_SAMPLE"] == "high"
    assert "SAMPLE_WITHIN_BOUNDS" not in found
    assert analysis.computed["sample_coverage_pct"] == Decimal("125.00")


async def test_policy_sample_size_and_tolerance(db: AsyncSession) -> None:
    analysis = await analyze(db, items_tested="10", documents=1, policy={"tolerable_exceptions": 2})

    found = codes(analysis)
    assert found["SAMPLE_TOO_SMALL"] == "warning"  # 10 < the default minimum of 25
    assert found["EXCEPTIONS_TOLERABLE"] == "warning"
    assert found["EVIDENCE_LINEAGE"] == "pass"
    assert analysis.headline == "Control test needs completion"

    # Testing the whole (small) population satisfies the minimum
    small = await analyze(db, population_count="10", items_tested="10", exceptions_found="0")
    assert codes(small)["SAMPLE_WITHIN_BOUNDS"] == "pass"
