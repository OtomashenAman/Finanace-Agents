from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.board_reporting import BoardReportingAgent
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's Board Reporting example
PDF_EXAMPLE = {
    "report_name": "Q3 Board Pack",
    "reporting_period": "2026-Q3",
    "reported_revenue": "1000000",
    "prior_period_revenue": "900000",
    "operating_profit": "150000",
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, BoardReportingAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_lacks_an_approved_source(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Source references missing"
    assert analysis.priority == RunPriority.HIGH
    assert codes(analysis) == {
        "MISSING_SOURCE_REFERENCE": "high",
        "NUMBERS_CONSISTENT": "pass",
        "NO_DISCLOSURES_RECORDED": "warning",
        "MISSING_EVIDENCE": "warning",
        "CFO_SIGN_OFF": "info",
    }
    assert analysis.computed == {
        "revenue_change": Decimal("100000"),
        "revenue_growth_pct": Decimal("11.11"),
        "operating_margin_pct": Decimal("15.00"),
    }
    labels = {c.key: c.label for c in analysis.calculations}
    assert labels["revenue_change"] == "Revenue increased by"


async def test_sourced_and_consistent_pack(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        source_dataset_id="CLOSE-2026-09-APPROVED",
        known_disclosures="No subsequent events",
    )

    assert analysis.headline == "Board figures consistent"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Approve all source claims and disclosures"
    assert codes(analysis)["SOURCE_REFERENCED"] == "pass"


async def test_inconsistent_numbers(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        source_dataset_id="SRC-1",
        reported_revenue="500000",
        operating_profit="600000",
        policy={"revenue_change_review_pct": "20"},
    )

    found = codes(analysis)
    assert analysis.headline == "Board figures inconsistent"
    assert found["PROFIT_EXCEEDS_REVENUE"] == "high"
    assert found["UNUSUAL_REVENUE_CHANGE"] == "warning"  # -44.44% vs the 20% threshold
    assert "NUMBERS_CONSISTENT" not in found
    assert calculation(analysis, "revenue_growth_pct") == Decimal("-44.44")
    labels = {c.key: c.label for c in analysis.calculations}
    assert labels["revenue_change"] == "Revenue decreased by"


async def test_zero_prior_period_has_no_growth(db: AsyncSession) -> None:
    analysis = await analyze(db, source_dataset_id="SRC-1", prior_period_revenue="0")

    assert codes(analysis)["NO_PRIOR_PERIOD"] == "warning"
    assert analysis.computed["revenue_growth_pct"] is None
