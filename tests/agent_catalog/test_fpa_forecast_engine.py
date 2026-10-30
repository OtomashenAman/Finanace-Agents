from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.fpa_forecast import FpaForecastAgent
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's FP&A example
PDF_EXAMPLE = {
    "business_unit": "North America",
    "forecast_period": "Q4 2026",
    "actual_value": "120000",
    "budget_value": "100000",
    "scenario_volume_pct": "5",
    "scenario_price_pct": "2",
    "scenario_cost_pct": "3",
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, FpaForecastAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_variance_and_scenario_bridge(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Budget variance"
    assert analysis.priority == RunPriority.HIGH
    assert codes(analysis) == {
        "VARIANCE_MATERIAL": "high",
        "MISSING_ASSUMPTIONS": "warning",
        "MISSING_EVIDENCE": "warning",
        "SCENARIO_VERSION": "info",
    }
    material = next(f for f in analysis.findings if f.code == "VARIANCE_MATERIAL")
    assert material.message == (
        "Actual vs budget variance of 20,000.00 (20%) exceeds the 10% materiality threshold"
    )
    # 120,000 +5% volume = +6,000; +2% price on 126,000 = +2,520; 3% cost = -3,600
    assert calculation(analysis, "volume_impact") == Decimal("6000.00")
    assert calculation(analysis, "price_impact") == Decimal("2520.00")
    assert calculation(analysis, "cost_impact") == Decimal("-3600.00")
    assert analysis.computed == {
        "variance": Decimal("20000"),
        "variance_pct": Decimal("20.00"),
        "scenario_value": Decimal("124920.00"),
    }


async def test_within_budget_with_assumptions(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        actual_value="104000",
        planning_assumptions="Volume from the Q4 pipeline; price list effective 1 Oct",
    )

    assert analysis.headline == "Within budget tolerance"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Scenario assumptions for approval"
    assert codes(analysis)["VARIANCE_WITHIN_THRESHOLD"] == "pass"
    assert codes(analysis)["ASSUMPTION_APPROVAL"] == "info"


async def test_unusual_scenario_and_no_budget(db: AsyncSession) -> None:
    unusual = await analyze(db, scenario_price_pct="-30", policy={"variance_materiality_pct": "25"})
    found = codes(unusual)
    assert found["UNUSUAL_SCENARIO"] == "warning"
    assert found["VARIANCE_WITHIN_THRESHOLD"] == "pass"  # 20% under the 25% setting

    no_budget = await analyze(db, budget_value="0")
    assert codes(no_budget)["NO_BUDGET"] == "warning"
    assert no_budget.computed["variance_pct"] is None
