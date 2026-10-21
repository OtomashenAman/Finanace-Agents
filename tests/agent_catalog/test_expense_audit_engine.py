from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.expense_audit import ExpenseAuditAgent
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import codes, run_analysis

# Values from the requirement deck's Expense Audit example
PDF_EXAMPLE = {
    "employee": "Jordan Smith",
    "merchant": "Northbridge Hotel",
    "claim_amount": "285.00",
    "policy_limit": "200.00",
    "receipt_total": "285.00",
    "receipt_provided": True,
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, ExpenseAuditAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_is_a_policy_exception(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Policy exception"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Request explanation or reject"
    assert codes(analysis) == {
        "RECEIPT_PROVIDED": "pass",
        "POLICY_LIMIT_EXCEEDED": "high",
        "AMOUNT_RECONCILED": "pass",
        "MISSING_EVIDENCE": "warning",
    }
    over = next(f for f in analysis.findings if f.code == "POLICY_LIMIT_EXCEEDED")
    assert over.message == "Claim 285.00 exceeds the 200.00 policy limit by 85.00"
    assert analysis.computed == {
        "over_limit_amount": Decimal("85.00"),
        "claim_vs_receipt": Decimal("0.00"),
    }


async def test_clean_claim(db: AsyncSession) -> None:
    analysis = await analyze(
        db, documents=1, claim_amount="180", receipt_total="180", card_transaction_id="TX-1"
    )

    assert analysis.headline == "Expense within policy"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Finance audit approval required"
    assert set(codes(analysis).values()) == {"pass"}
    assert "DUPLICATE_CHECK_CLEAR" in codes(analysis)


async def test_missing_receipt_and_amount_mismatch(db: AsyncSession) -> None:
    no_receipt = await analyze(db, receipt_provided=False, receipt_total=None, claim_amount="150")
    assert codes(no_receipt)["MISSING_RECEIPT"] == "high"
    assert no_receipt.headline == "Expense exception"

    mismatch = await analyze(db, claim_amount="190", receipt_total="150")
    assert codes(mismatch)["AMOUNT_MISMATCH"] == "high"

    tolerated = await analyze(
        db, claim_amount="190", receipt_total="189.50", policy={"receipt_tolerance": "1"}
    )
    assert codes(tolerated)["AMOUNT_RECONCILED"] == "pass"

    no_total = await analyze(db, claim_amount="150", receipt_total=None)
    assert codes(no_total)["MISSING_RECEIPT_TOTAL"] == "warning"


async def test_card_transaction_already_claimed(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        claim_amount="150",
        receipt_total="150",
        card_transaction_id="tx-77",
        prior_card_transaction_ids="TX-10, TX-77\nTX-90",
    )

    assert analysis.headline == "Duplicate card transaction"
    assert codes(analysis)["DUPLICATE_CARD_TRANSACTION"] == "high"
