from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from pydantic import BaseModel

from src.app.agent_catalog.agents.ar_collections import prompt
from src.app.agent_catalog.agents.ar_collections.models import ArCollectionsRun
from src.app.agent_catalog.agents.ar_collections.schemas import (
    ArCollectionsInput,
    ArCollectionsPolicy,
)
from src.app.agent_catalog.agents.base import (
    Analysis,
    AnalysisContext,
    BaseAgent,
    Calculation,
    Finding,
)
from src.app.agent_catalog.agents.checks import evidence_check, money
from src.app.agent_catalog.runs.models import FlagSeverity

# Priority score points (0-100): aging bucket, plus exposure, plus late payment history
AGING_POINTS = (
    (0, "Current", 0),
    (30, "1-30", 10),
    (60, "31-60", 30),
    (90, "61-90", 50),
)
OVER_90 = ("90+", 70)
EXPOSURE_POINTS = 10
LATE_PAYMENT_POINTS = 5
MAX_LATE_PAYMENT_POINTS = 20

HOLD = "Hold - resolve dispute"
ESCALATE = "Escalate"
REMIND = "Send reminder"
MONITOR = "Monitor"


@dataclass(frozen=True)
class Priority:
    bucket: str
    score: int
    action: str


def priority(data: ArCollectionsInput, policy: ArCollectionsPolicy) -> Priority:
    """Deterministic score and next-best action; an open dispute always means hold."""
    bucket, points = next(
        ((label, pts) for limit, label, pts in AGING_POINTS if data.days_overdue <= limit),
        OVER_90,
    )
    if policy.high_exposure_amount is not None and data.open_balance > policy.high_exposure_amount:
        points += EXPOSURE_POINTS
    points += min(data.previous_late_payments * LATE_PAYMENT_POINTS, MAX_LATE_PAYMENT_POINTS)
    score = min(points, 100)
    if data.open_dispute:
        action = HOLD
    elif score >= policy.escalate_score:
        action = ESCALATE
    elif score >= policy.reminder_score:
        action = REMIND
    else:
        action = MONITOR
    return Priority(bucket, score, action)


class ArCollectionsAgent(BaseAgent):
    key = "ar_collections"
    code = "03"
    name = "AR Collections Prioritization & Dunning"
    short_name = "AR Collections"
    description = "Score aged receivables and draft an appropriate collector communication."
    primary_user = "AR Collector"
    reviewer = "Collections Lead"

    input_schema = ArCollectionsInput
    run_model = ArCollectionsRun
    reference_field = "customer"
    policy_version = "ar_collections/v1"
    controls = (
        "Overdue aging",
        "Exposure",
        "Dispute block",
        "Strategic account communication",
    )
    narrative_guidance = prompt.GUIDANCE
    prompt_version = prompt.PROMPT_VERSION
    draft_message = (
        "Payment reminder email to the customer, or an internal note if there is an open dispute"
    )
    policy_schema = ArCollectionsPolicy
    approval_amount_label = "Open balance"

    @classmethod
    def approval_amount(cls, data: BaseModel) -> Decimal | None:
        return cast(ArCollectionsInput, data).open_balance

    @classmethod
    async def analyze(cls, data: BaseModel, ctx: AnalysisContext) -> Analysis:
        ar = cast(ArCollectionsInput, data)
        policy = cast(ArCollectionsPolicy, ctx.policy) if ctx.policy else ArCollectionsPolicy()
        result = priority(ar, policy)
        findings: list[Finding] = []

        if ar.days_overdue == 0:
            findings.append(
                Finding("NOT_OVERDUE", FlagSeverity.PASS, "Balance is not overdue", "days_overdue")
            )
        else:
            findings.append(
                Finding(
                    "OVERDUE_AGING",
                    FlagSeverity.HIGH if result.bucket == OVER_90[0] else FlagSeverity.WARNING,
                    f"{ar.days_overdue} days overdue ({result.bucket} day bucket)",
                    "days_overdue",
                )
            )

        exposure = policy.high_exposure_amount
        if exposure is not None and ar.open_balance > exposure:
            findings.append(
                Finding(
                    "HIGH_EXPOSURE",
                    FlagSeverity.WARNING,
                    f"Open balance {money(ar.open_balance)} is above the {money(exposure)} "
                    "high exposure level",
                    "open_balance",
                )
            )
        else:
            findings.append(
                Finding(
                    "EXPOSURE_NORMAL",
                    FlagSeverity.PASS,
                    f"Open balance {money(ar.open_balance)} is within normal exposure",
                    "open_balance",
                )
            )

        if ar.open_dispute:
            findings.append(
                Finding(
                    "DISPUTE_BLOCK",
                    FlagSeverity.HIGH,
                    "Open dispute: no dunning until the dispute is resolved",
                    "open_dispute",
                )
            )
        else:
            findings.append(
                Finding("NO_DISPUTE", FlagSeverity.PASS, "No open dispute", "open_dispute")
            )
        if ar.strategic_account:
            findings.append(
                Finding(
                    "STRATEGIC_ACCOUNT",
                    FlagSeverity.WARNING,
                    "Strategic account: customer communication needs the collections lead's "
                    "approval",
                    "strategic_account",
                )
            )
        if ar.promise_to_pay:
            findings.append(
                Finding(
                    "PROMISE_TO_PAY",
                    FlagSeverity.INFO,
                    "Promise to pay recorded: follow up on it before escalating",
                    "promise_to_pay",
                )
            )
        evidence = evidence_check(ctx, "customer statement or invoices")
        if evidence is not None:
            findings.append(evidence)

        headline = {
            HOLD: "Collections on hold: dispute",
            ESCALATE: "Escalate collection",
            REMIND: "Collections priority",
            MONITOR: "Monitor account",
        }[result.action]
        decision = {
            HOLD: "Resolve the dispute before any dunning",
            ESCALATE: "Approve escalation and the draft communication",
            REMIND: "Draft reminder for human approval",
            MONITOR: "No dunning now: reviewer confirms",
        }[result.action]
        return Analysis(
            headline=headline,
            proposed_decision=decision,
            calculations=[
                Calculation("open_balance", "Open balance", ar.open_balance),
                Calculation("days_overdue", "Days overdue", str(ar.days_overdue), "number"),
                Calculation("aging_bucket", "Aging bucket (days)", result.bucket, "text"),
                Calculation(
                    "previous_late_payments",
                    "Previous late payments",
                    str(ar.previous_late_payments),
                    "number",
                ),
                Calculation(
                    "priority_score", "Priority score (0-100)", str(result.score), "number"
                ),
                Calculation("next_action", "Next-best action", result.action, "text"),
            ],
            findings=findings,
            computed={
                "aging_bucket": result.bucket,
                "priority_score": result.score,
                "next_action": result.action,
            },
        )
