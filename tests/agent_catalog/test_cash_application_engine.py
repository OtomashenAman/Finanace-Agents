from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.cash_application import CashApplicationAgent
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import codes, run_analysis

# Values from the requirement deck's Cash Application example
PDF_EXAMPLE = {
    "customer": "Harbor Distribution",
    "payment_reference": "WIRE-2901",
    "payment_amount": "900.00",
    "candidate_invoice_number": "INV-8021",
    "invoice_open_amount": "1000.00",
    "reference_verified": True,
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, CashApplicationAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_is_a_short_payment_to_classify(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Short payment"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Deduction requires classification"
    assert codes(analysis) == {
        "DUPLICATE_CHECK_CLEAR": "pass",
        "INVOICE_REFERENCE_MATCH": "pass",
        "SHORT_PAYMENT": "warning",
        "DEDUCTION_REVIEW": "high",
        "AMBIGUOUS_REMITTANCE": "warning",
        "MISSING_EVIDENCE": "warning",
    }
    short = next(f for f in analysis.findings if f.code == "SHORT_PAYMENT")
    assert short.message == "Payment is 100.00 short of the invoice open amount 1,000.00"
    assert analysis.computed == {"short_payment": Decimal("100.00")}


async def test_exact_match(db: AsyncSession) -> None:
    analysis = await analyze(db, documents=1, payment_amount="1000.00")

    assert analysis.headline == "Payment matches invoice"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Cash application reviewer approval required"
    assert set(codes(analysis).values()) == {"pass"}


async def test_small_deduction_and_tolerance(db: AsyncSession) -> None:
    small = await analyze(
        db,
        documents=1,
        remittance_advice="Short paid: damaged pallet",
        policy={"match_tolerance": "0", "deduction_review_amount": "250"},
    )
    found = codes(small)
    assert found["DEDUCTION_BELOW_THRESHOLD"] == "info"
    assert "AMBIGUOUS_REMITTANCE" not in found
    assert small.priority == RunPriority.NORMAL

    tolerated = await analyze(db, payment_amount="999.50", policy={"match_tolerance": "1"})
    assert codes(tolerated)["AMOUNT_MATCH"] == "pass"


async def test_overpayment_and_unverified_reference(db: AsyncSession) -> None:
    analysis = await analyze(db, payment_amount="1100.00", reference_verified=False)

    assert analysis.headline == "Overpayment"
    found = codes(analysis)
    assert found["OVERPAYMENT"] == "warning"
    assert found["REFERENCE_NOT_VERIFIED"] == "warning"
    assert analysis.computed["short_payment"] == Decimal("-100.00")
