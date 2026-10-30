from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.financial_close import FinancialCloseAgent
from src.app.agent_catalog.agents.financial_close.schemas import FinancialCloseInput
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import codes, run_analysis

# Values from the requirement deck's Financial Close example
PDF_EXAMPLE = {
    "gl_account": "1200-AR-Control",
    "close_period": "2026-09",
    "gl_balance": "120000",
    "subledger_balance": "119000",
    "materiality_threshold": "500",
}


async def analyze(db: AsyncSession, documents: int = 0, **overrides: object) -> Analysis:
    return await run_analysis(
        db, FinancialCloseAgent, {**PDF_EXAMPLE, **overrides}, documents=documents
    )


async def test_pdf_example_is_a_material_variance(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Material close variance"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Reconciliation review required"
    assert codes(analysis) == {
        "DUPLICATE_CHECK_CLEAR": "pass",
        "BALANCE_MISMATCH": "warning",
        "MATERIAL_VARIANCE": "high",
        "MISSING_RATIONALE": "warning",
        "MISSING_EVIDENCE": "warning",
        "PREPARER_REVIEWER_SEPARATION": "info",
    }
    material = next(f for f in analysis.findings if f.code == "MATERIAL_VARIANCE")
    assert material.message == (
        "Unexplained difference 1,000.00 exceeds the 500.00 materiality threshold"
    )
    assert analysis.computed == {
        "variance": Decimal("1000"),
        "unexplained_difference": Decimal("1000"),
    }


async def test_reconciling_items_explain_the_difference(db: AsyncSession) -> None:
    analysis = await analyze(db, documents=1, known_reconciling_items="1000")

    assert analysis.headline == "Account reconciled"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Controller sign-off required"
    match = next(f for f in analysis.findings if f.code == "BALANCE_MATCH")
    assert match.message == "Known reconciling items explain the 1,000.00 difference in full"
    assert analysis.computed["unexplained_difference"] == Decimal("0")


async def test_immaterial_difference_with_rationale(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        known_reconciling_items="700",
        proposed_adjustment_rationale="Bank fee not yet booked",
    )

    assert analysis.headline == "Immaterial close variance"
    found = codes(analysis)
    assert found["WITHIN_MATERIALITY"] == "pass"
    assert "MISSING_RATIONALE" not in found
    mismatch = next(f for f in analysis.findings if f.code == "BALANCE_MISMATCH")
    assert mismatch.message == (
        "GL 120,000.00 vs subledger 119,000.00: 300.00 unexplained after 700.00 of known "
        "reconciling items"
    )


def test_close_period_must_be_a_month() -> None:
    with pytest.raises(ValidationError):
        FinancialCloseInput.model_validate({**PDF_EXAMPLE, "close_period": "2026-13"})
