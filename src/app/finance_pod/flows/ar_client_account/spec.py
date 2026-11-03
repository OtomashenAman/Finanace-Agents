"""AR-1 Client Account & Credit Set-Up (GIA drill-down page 16)."""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.flows.ar_client_account import agents, service
from src.app.finance_pod.flows.ar_client_account.results import (
    Application,
    ClientCreated,
    CreditDecision,
    CreditProposal,
    DocumentsChecked,
    DocumentsUploaded,
    Gaps,
    InSync,
    LimitReview,
    RiskScore,
    Screening,
)
from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.steps.spec import (
    L5Spec,
    Measure,
    Rule,
    StepKind,
    StepPlan,
    StepSpec,
)
from src.app.service_pod.core.workflows import PodKey, WorkflowKey, WorkflowSpec

AGENT, PERSON = StepKind.AGENT, StepKind.PERSON
CREDIT = Cap.CREDIT_CONTROLLER.value
DESK = frozenset({CREDIT, Cap.BILLING_ANALYST.value})

STEPS = (
    # The client is the person of 1.1.1: their portal submission completes it. A credit
    # controller can complete it for a client who applied on paper.
    StepSpec("1.1.1", "1.1.1", "Client applies", PERSON, (
        L5Spec("1.1.1.a", "Completes portal form", Application),
        L5Spec("1.1.1.b", "Uploads documents", DocumentsUploaded),
    ), capacity=CREDIT),
    StepSpec("1.1.2", "1.1.2", "Onboarding agent", AGENT, (
        L5Spec("1.1.2.a", "Reads and validates documents", DocumentsChecked),
        L5Spec("1.1.2.b", "Runs compliance screening", Screening),
        L5Spec("1.1.2.c", "Flags gaps to client", Gaps),
    ), after=("1.1.1",), handler=agents.onboard, run_by=DESK, ready=agents.ready_to_onboard),
    StepSpec("1.2.1", "1.2.1", "Credit agent", AGENT, (
        L5Spec("1.2.1.a", "Scores risk from data", RiskScore),
        L5Spec("1.2.1.b", "Proposes limit or deposit", CreditProposal),
    ), after=("1.1.2",), handler=agents.score, run_by=DESK),
    StepSpec("1.2.2", "1.2.2", "Credit controller", PERSON, (
        L5Spec("1.2.2.a", "Approves terms and limit", CreditDecision),
    ), capacity=CREDIT, after=("1.2.1",), distinct_from=("1.1.1",),
       on_done=service.after_decision),
    # After the decision (the release): the client in the ERP, and its limit watched
    StepSpec("1.3.1", "1.3.1", "Set up once", AGENT, (
        L5Spec("1.3.1.a", "Creates client in both systems", ClientCreated),
        L5Spec("1.3.1.b", "Keeps them in sync", InSync),
    ), after=("1.2.2",), handler=agents.set_up, run_by=DESK, after_approval=True,
       on_done=service.after_set_up),
    StepSpec("1.3.2", "1.3.2", "Monitor", AGENT, (
        L5Spec("1.3.2.a", "Reviews limits as history builds", LimitReview),
    ), after=("1.3.1",), handler=agents.monitor, run_by=DESK, after_approval=True),
)  # fmt: skip

RULES = (
    Rule("AR1.R1", "Credit limits approved by finance",
         enforced_by="1.2.2 is the credit controller's; the client is created in the ERP with "
                     "exactly the limit and terms they approved"),
    Rule("AR1.R2", "New clients may start on deposit",
         enforced_by="1.2.1.b proposes deposit only for a client who asks for it, has too few "
                     "trade references or a high risk; 1.2.2 may choose deposit only"),
    Rule("AR1.R3", "Accounts reviewed periodically",
         enforced_by="1.3.2 reviews the limit once the client exists, and a daily job again on "
                     "the newest snapshot (a review task when it's nearly used or long overdue)"),
    Rule("AR1.G1", "No credit without human approval", check=service.human_approval_rule,
         enforced_by="the customer is only posted on release, after 1.2.2, with the "
                     "controller's terms (never the agent's proposal)"),
    Rule("AR1.P1", "Set-up done twice: ERP and lab system",
         enforced_by="1.3.1 creates the client once, from the approved application, with the "
                     "app's reference (a retry finds it); the lab system isn't connected yet, "
                     "and 1.3.1.a says so"),
    Rule("AR1.P2", "Limits rarely reviewed",
         enforced_by="the daily limit review (AR1.R3)"),
    Rule("AR1.P3", "Documents held in email", check=service.documents_from_portal_rule,
         enforced_by="the client uploads through the portal into the case; an email "
                     "attachment never counts"),
)  # fmt: skip

SPEC = WorkflowSpec(
    key=WorkflowKey.AR_CLIENT_ACCOUNT,
    name="Client Account & Credit",
    prefix="CLT",
    description=(
        "A new client applies through a secure portal; their documents are read and screened, "
        "gaps go back to them, the credit agent scores the risk and proposes a limit or a "
        "deposit, the credit controller decides, and the client goes to ERPNext."
    ),
    required=frozenset({Collection.CLIENTS}),
    signoffs=(),
    pod=PodKey.FINANCE,
    plan=StepPlan(
        steps=STEPS,
        rules=RULES,
        measures=(
            Measure("AR1.M1", "Account set-up time", "days", service.setup_time),
            Measure("AR1.M2", "Data errors", "%", service.data_errors),
        ),
        viewers=DESK,
        openers=DESK,
        on_release=service.create_customer,
        senders={
            "client_invite": DESK,
            "client_gaps": DESK,
        },
        posters={"create_customer": frozenset({CREDIT})},
    ),
)
