from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.revenue_recognition import RevenueRecognitionAgent
from src.app.agent_catalog.agents.revenue_recognition.agent import obligations, service_months
from src.app.agent_catalog.agents.revenue_recognition.schemas import RevenueRecognitionInput
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's Revenue Recognition example
PDF_EXAMPLE = {
    "customer": "Futura Technologies",
    "contract_id": "CTR-2026-091",
    "contract_total": "120000",
    "service_term_months": "12",
    "performance_obligations": "Hosting and support",
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db,
        RevenueRecognitionAgent,
        {**PDF_EXAMPLE, **overrides},
        documents=documents,
        policy=policy,
    )


async def test_pdf_example_needs_obligation_and_policy_review(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Allocation across obligations needed"
    assert analysis.priority == RunPriority.HIGH
    assert analysis.proposed_decision == "Needs obligation and policy review"
    assert codes(analysis) == {
        "MULTIPLE_OBLIGATIONS": "high",
        "FIXED_CONSIDERATION": "pass",
        "POLICY_REVIEW": "warning",
        "MISSING_CONTRACT_CLAUSES": "warning",
        "MISSING_EVIDENCE": "warning",
        "PRELIMINARY_ILLUSTRATION": "info",
    }
    # "Illustrative even allocation: $10,000/month"
    assert calculation(analysis, "monthly_revenue") == Decimal("10000.00")
    assert analysis.computed == {"monthly_revenue": Decimal("10000.00"), "obligation_count": 2}


async def test_single_obligation_below_policy_needs_only_sign_off(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        contract_total="60000",
        performance_obligations="Hosting",
        contract_clauses="12-month hosting, billed annually in advance",
    )

    assert analysis.headline == "Single-obligation contract"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Revenue controller sign-off required"
    assert set(codes(analysis).values()) == {"pass", "info"}


async def test_rounding_goes_to_the_final_month(db: AsyncSession) -> None:
    analysis = await analyze(db, contract_total="100000", service_term_months="3")

    assert calculation(analysis, "monthly_revenue") == Decimal("33333.33")
    assert calculation(analysis, "final_month_revenue") == Decimal("33333.34")


async def test_variable_consideration_and_contract_changes(db: AsyncSession) -> None:
    analysis = await analyze(
        db, variable_consideration="Usage fees above 1 TB; amended in month 6 to add storage"
    )

    found = codes(analysis)
    assert found["VARIABLE_CONSIDERATION"] == "warning"
    assert found["CONTRACT_CHANGES"] == "warning"
    assert "FIXED_CONSIDERATION" not in found


async def test_variable_consideration_without_a_change(db: AsyncSession) -> None:
    analysis = await analyze(db, variable_consideration="5% volume rebate")

    found = codes(analysis)
    assert found["VARIABLE_CONSIDERATION"] == "warning"
    assert "CONTRACT_CHANGES" not in found


async def test_policy_review_can_be_turned_off(db: AsyncSession) -> None:
    analysis = await analyze(db, policy={"policy_review_amount": None})  # type: ignore[dict-item]

    assert "POLICY_REVIEW" not in codes(analysis)


def test_obligations_are_split_on_lines_and_lists() -> None:
    assert obligations("Hosting and support") == ["Hosting", "support"]
    assert obligations("Hosting: 90,000.00\nSupport: 30,000.00") == [
        "Hosting: 90,000.00",
        "Support: 30,000.00",
    ]
    assert obligations("- Licence; - Training, Support") == ["Licence", "Training", "Support"]
    assert obligations("Hosting") == ["Hosting"]


def test_service_months_counts_both_ends() -> None:
    assert service_months(date(2026, 1, 1), date(2026, 12, 1)) == 12
    assert service_months(date(2026, 1, 1), date(2026, 1, 31)) == 1
    assert service_months(date(2026, 3, 1), None) is None
    assert service_months(date(2026, 3, 1), date(2026, 2, 1)) is None


def test_approval_routes_on_the_contract_total() -> None:
    data = RevenueRecognitionInput.model_validate(PDF_EXAMPLE)
    assert RevenueRecognitionAgent.approval_amount(data) == Decimal("120000")
