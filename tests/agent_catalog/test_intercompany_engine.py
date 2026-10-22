from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.intercompany import IntercompanyAgent
from src.app.agent_catalog.agents.intercompany.schemas import IntercompanyInput
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's Intercompany example
PDF_EXAMPLE = {
    "sending_entity": "US Subsidiary",
    "receiving_entity": "UK Subsidiary",
    "currency": "USD",
    "intercompany_ar": "50000",
    "counterparty_ap": "49000",
    "translation_rate": "1",
    "matching_tolerance": "100",
}


async def analyze(db: AsyncSession, documents: int = 0, **overrides: object) -> Analysis:
    return await run_analysis(
        db, IntercompanyAgent, {**PDF_EXAMPLE, **overrides}, documents=documents
    )


async def test_pdf_example_is_an_intercompany_mismatch(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Intercompany mismatch"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Resolve before settlement"
    assert codes(analysis) == {
        "IC_MISMATCH": "high",
        "NO_TRANSLATION": "pass",
        "TRANSFER_PRICING_REVIEW": "warning",
        "MISSING_EVIDENCE": "warning",
        "SETTLEMENT_AUTHORIZATION": "info",
    }
    mismatch = next(f for f in analysis.findings if f.code == "IC_MISMATCH")
    assert mismatch.message == (
        "Intercompany AR differs from the translated counterparty AP by 1,000.00"
    )
    assert analysis.computed == {
        "translated_ap": Decimal("49000.00"),
        "difference": Decimal("1000.00"),
        "nettable_amount": Decimal("49000.00"),
    }


async def test_translated_balances_match_within_tolerance(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        counterparty_ap="40000",
        translation_rate="1.2512",
        transfer_pricing_notes="Cost plus 5% service agreement",
    )

    # 40,000 x 1.2512 = 50,048.00: 48.00 under the 100 tolerance
    assert calculation(analysis, "translated_ap") == Decimal("50048.00")
    assert codes(analysis)["IC_MATCH"] == "pass"
    assert codes(analysis)["FX_ASSUMPTION"] == "warning"
    assert analysis.headline == "Intercompany match needs review"
    assert analysis.proposed_decision == "Netting proposal for authorization"


async def test_same_entity_is_an_exception(db: AsyncSession) -> None:
    analysis = await analyze(db, receiving_entity="us subsidiary", counterparty_ap="50000")

    assert codes(analysis)["SAME_ENTITY"] == "high"
    assert analysis.headline == "Intercompany exception"


def test_translation_rate_must_be_positive_with_8_decimals_at_most() -> None:
    for rate in ("0", "-1", "1.123456789"):
        with pytest.raises(ValidationError):
            IntercompanyInput.model_validate({**PDF_EXAMPLE, "translation_rate": rate})
