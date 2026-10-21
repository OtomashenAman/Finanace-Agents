import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.agent_catalog.agents.ar_collections import ArCollectionsAgent
from src.app.agent_catalog.agents.ar_collections.agent import priority
from src.app.agent_catalog.agents.ar_collections.schemas import (
    ArCollectionsInput,
    ArCollectionsPolicy,
)
from src.app.agent_catalog.agents.base import Analysis
from src.app.agent_catalog.runs.models import RunPriority
from tests.agent_catalog.engine import calculation, codes, run_analysis

# Values from the requirement deck's AR Collections example
PDF_EXAMPLE = {
    "customer": "Harbor Distribution",
    "open_balance": "25000",
    "days_overdue": "45",
    "previous_late_payments": "2",
    "open_dispute": False,
}


async def analyze(
    db: AsyncSession, documents: int = 0, policy: dict[str, str] | None = None, **overrides: object
) -> Analysis:
    return await run_analysis(
        db, ArCollectionsAgent, {**PDF_EXAMPLE, **overrides}, documents=documents, policy=policy
    )


async def test_pdf_example_proposes_a_reminder(db: AsyncSession) -> None:
    analysis = await analyze(db)

    # 31-60 days = 30 points, 2 late payments = 10 points
    assert calculation(analysis, "priority_score") == "40"
    assert calculation(analysis, "aging_bucket") == "31-60"
    assert analysis.headline == "Collections priority"
    assert analysis.proposed_decision == "Draft reminder for human approval"
    assert analysis.priority == RunPriority.NORMAL
    assert codes(analysis) == {
        "OVERDUE_AGING": "warning",
        "EXPOSURE_NORMAL": "pass",
        "NO_DISPUTE": "pass",
        "MISSING_EVIDENCE": "warning",
    }
    assert analysis.computed == {
        "aging_bucket": "31-60",
        "priority_score": 40,
        "next_action": "Send reminder",
    }


async def test_open_dispute_always_holds(db: AsyncSession) -> None:
    analysis = await analyze(db, days_overdue="120", open_dispute=True)

    assert analysis.headline == "Collections on hold: dispute"
    assert analysis.proposed_decision == "Resolve the dispute before any dunning"
    assert codes(analysis)["DISPUTE_BLOCK"] == "high"
    assert codes(analysis)["OVERDUE_AGING"] == "high"  # 90+ bucket
    assert analysis.computed["next_action"] == "Hold - resolve dispute"


async def test_escalation_strategic_and_promise(db: AsyncSession) -> None:
    analysis = await analyze(
        db,
        documents=1,
        open_balance="80000",
        days_overdue="75",
        strategic_account=True,
        promise_to_pay="Pays on 30 Oct",
    )

    # 61-90 = 50, exposure above 50,000 = 10, 2 late payments = 10
    assert analysis.computed["priority_score"] == 70
    assert analysis.headline == "Escalate collection"
    found = codes(analysis)
    assert found["HIGH_EXPOSURE"] == "warning"
    assert found["STRATEGIC_ACCOUNT"] == "warning"
    assert found["PROMISE_TO_PAY"] == "info"


@pytest.mark.parametrize(
    ("days", "late", "score", "action"),
    [
        (0, 0, 0, "Monitor"),
        (10, 1, 15, "Monitor"),
        (30, 4, 30, "Send reminder"),
        (91, 0, 70, "Escalate"),
        (400, 10, 90, "Escalate"),  # late payment points capped at 20
    ],
)
def test_priority_score_rules(days: int, late: int, score: int, action: str) -> None:
    data = ArCollectionsInput.model_validate(
        {**PDF_EXAMPLE, "days_overdue": days, "previous_late_payments": late}
    )
    result = priority(data, ArCollectionsPolicy())
    assert (result.score, result.action) == (score, action)


async def test_policy_moves_the_action_thresholds(db: AsyncSession) -> None:
    analysis = await analyze(db, policy={"reminder_score": "50", "escalate_score": "80"})

    assert analysis.computed["next_action"] == "Monitor"  # 40 is now under the reminder score
