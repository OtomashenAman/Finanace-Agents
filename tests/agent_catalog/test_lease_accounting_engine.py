from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.agents.lease_accounting import LeaseAccountingAgent
from src.app.agent_catalog.agents.lease_accounting.agent import lease_liability
from src.app.agent_catalog.agents.lease_accounting.schemas import LeaseAccountingInput
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's Lease Accounting example
PDF_EXAMPLE = {
    "lessor": "Central Offices",
    "leased_asset": "Headquarters space",
    "monthly_payment": "5000",
    "remaining_term_months": "24",
    "annual_discount_rate": "6",
}


async def analyze(
    db: AsyncSession,
    documents: int = 0,
    policy: dict[str, object] | None = None,
    **overrides: object,
) -> Analysis:
    return await run_analysis(
        db, LeaseAccountingAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_needs_classification_and_assumption_review(db: AsyncSession) -> None:
    analysis = await analyze(db)

    assert analysis.headline == "Lease schedule"
    assert analysis.priority == RunPriority.NORMAL
    assert analysis.proposed_decision == "Classification and assumptions need review"
    assert codes(analysis) == {
        "LEASE_CLASSIFICATION": "info",
        "DISCOUNT_RATE_IN_RANGE": "pass",
        "NO_OPTIONS_RECORDED": "warning",
        "NO_EARLIER_RUN": "pass",
        "MISSING_LEASE_CLAUSES": "warning",
        "MISSING_EVIDENCE": "warning",
    }
    # 5,000 a month for 24 months at 0.5% a month, paid in arrears
    assert analysis.computed == {
        "lease_liability": Decimal("112814.33"),
        "right_of_use_asset": Decimal("112814.33"),
        "total_interest": Decimal("7185.67"),
    }
    assert calculation(analysis, "total_payments") == Decimal("120000")


async def test_initial_direct_costs_add_to_the_right_of_use_asset(db: AsyncSession) -> None:
    analysis = await analyze(db, initial_direct_costs="2500")

    assert analysis.computed["right_of_use_asset"] == Decimal("115314.33")
    assert analysis.computed["lease_liability"] == Decimal("112814.33")


async def test_recorded_options_still_need_review(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        renewal_termination_options="None",
        lease_clauses="Rent fixed for the term; no purchase option",
    )

    assert codes(analysis)["RENEWAL_TERMINATION_OPTIONS"] == "warning"


async def test_zero_rate_is_an_exception(db: AsyncSession) -> None:
    analysis = await analyze(db, annual_discount_rate="0")

    assert analysis.headline == "Lease assumptions incomplete"
    assert analysis.priority == RunPriority.HIGH
    assert codes(analysis)["NO_DISCOUNT_RATE"] == "high"
    assert analysis.computed["lease_liability"] == Decimal("120000.00")
    assert analysis.computed["total_interest"] == Decimal("0.00")


async def test_rate_outside_the_expected_range(db: AsyncSession) -> None:
    analysis = await analyze(db, annual_discount_rate="18")

    assert codes(analysis)["DISCOUNT_RATE_OUT_OF_RANGE"] == "warning"


async def test_short_term_lease(db: AsyncSession) -> None:
    analysis = await analyze(db, remaining_term_months="9")

    assert analysis.headline == "Short-term lease"
    found = codes(analysis)
    assert found["SHORT_TERM_LEASE"] == "info"
    assert "LEASE_CLASSIFICATION" not in found


async def test_no_exemption_when_the_policy_turns_it_off(db: AsyncSession) -> None:
    analysis = await analyze(db, remaining_term_months="9", policy={"short_term_months": None})

    assert "SHORT_TERM_LEASE" not in codes(analysis)


def test_liability_is_the_present_value_of_the_payments() -> None:
    assert lease_liability(Decimal("1000"), 12, Decimal("0")) == Decimal("12000.00")
    assert lease_liability(Decimal("1000"), 1, Decimal("12")) == Decimal("990.10")


def test_approval_routes_on_the_lease_liability() -> None:
    data = LeaseAccountingInput.model_validate(PDF_EXAMPLE)
    assert LeaseAccountingAgent.approval_amount(data) == Decimal("112814.33")
