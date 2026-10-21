from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.treasury_cash import TreasuryCashAgent
from src.app.agent_catalog.agents.treasury_cash.schemas import TreasuryCashInput
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's Treasury example
PDF_EXAMPLE = {
    "currency": "USD",
    "opening_cash": "250000",
    "expected_inflows": "150000",
    "expected_outflows": "300000",
    "minimum_liquidity_buffer": "125000",
    "forecast_horizon_days": "30",
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, TreasuryCashAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_is_below_the_liquidity_buffer(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Liquidity shortfall"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Check buffer limits before action"
    assert codes(analysis) == {
        "PROJECTED_CASH_POSITIVE": "pass",
        "LIQUIDITY_BUFFER": "high",
        "DUAL_AUTHORIZATION": "warning",
        "NO_FUNDING_OPTIONS": "warning",
        "MISSING_EVIDENCE": "warning",
    }
    buffer = next(f for f in analysis.findings if f.code == "LIQUIDITY_BUFFER")
    assert buffer.message == (
        "Projected closing cash 100,000.00 is 25,000.00 below the 125,000.00 minimum "
        "liquidity buffer"
    )
    assert analysis.computed == {
        "closing_cash": Decimal("100000"),
        "funding_gap": Decimal("25000"),
    }
    assert calculation(analysis, "closing_cash") == Decimal("100000")


async def test_negative_cash_is_its_own_exception(db: AsyncSession) -> None:
    analysis = await analyze(db, expected_outflows="450000", permitted_funding_options="Revolver")

    assert analysis.headline == "Negative cash projected"
    found = codes(analysis)
    assert found["NEGATIVE_PROJECTED_CASH"] == "high"
    assert found["LIQUIDITY_BUFFER"] == "high"
    assert "NO_FUNDING_OPTIONS" not in found
    assert analysis.computed["closing_cash"] == Decimal("-50000")
    assert analysis.computed["funding_gap"] == Decimal("175000")


async def test_buffer_held_needs_only_sign_off(db: AsyncSession) -> None:
    analysis = await analyze(db, documents=1, expected_outflows="200000")

    assert analysis.headline == "Liquidity within buffer"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Treasury approver sign-off required"
    assert set(codes(analysis).values()) == {"pass"}
    assert analysis.computed["funding_gap"] == Decimal("0.00")


def test_approval_routes_on_the_funding_gap() -> None:
    data = TreasuryCashInput.model_validate(PDF_EXAMPLE)
    assert TreasuryCashAgent.approval_amount(data) == Decimal("25000")


async def test_policy_dual_authorization_and_large_outflows(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        permitted_funding_options="Revolver draw",
        policy={"dual_authorization_amount": "50000", "large_outflow_amount": "250000"},
    )

    found = codes(analysis)
    assert "DUAL_AUTHORIZATION" not in found  # 25,000 gap is under the 50,000 rule
    assert found["LARGE_OUTFLOWS"] == "warning"
