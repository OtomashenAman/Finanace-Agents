"""AP-6 Month-End Close (GIA drill-down pages 13-14): L3 6.1 and 6.2, one case per entity
and month. The close agent lists what was received and not invoiced and proposes the accrual,
reconciles the payables subledger to the ledger and reads the vendor statements; the
controller reviews and signs off, the evidence pack is filed, and the controller posts the
proposed journals (the agent never posts, AP6.G1)."""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.flows.ap_month_close import agents, service
from src.app.finance_pod.flows.ap_month_close.results import (
    AccrualProposal,
    Explanation,
    ReceiptsNotInvoiced,
    Review,
    SignOff,
    StatementCheck,
    SubledgerVsLedger,
)
from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.steps.spec import (
    OWNER,
    L5Spec,
    Measure,
    Rule,
    StepKind,
    StepPlan,
    StepSpec,
)
from src.app.service_pod.core.workflows import PodKey, WorkflowKey, WorkflowSpec

AGENT, PERSON = StepKind.AGENT, StepKind.PERSON
CLOSERS = frozenset({Cap.AP_ANALYST.value, Cap.CONTROLLER.value})

STEPS = (
    StepSpec("6.1.1", "6.1.1", "Accruals", AGENT, (
        L5Spec("6.1.1.a", "Lists receipts not invoiced", ReceiptsNotInvoiced),
        L5Spec("6.1.1.b", "Proposes accrual journal", AccrualProposal),
    ), handler=agents.accruals, run_by=CLOSERS),
    StepSpec("6.1.2", "6.1.2", "Reconcile", AGENT, (
        L5Spec("6.1.2.a", "Subledger vs ledger daily", SubledgerVsLedger),
        L5Spec("6.1.2.b", "Explains differences", Explanation),
    ), after=("6.1.1",), handler=agents.reconcile_step, run_by=CLOSERS),
    StepSpec("6.1.3", "6.1.3", "Vendor statements", AGENT, (
        L5Spec("6.1.3.a", "Reads statements; flags gaps", StatementCheck),
    ), after=("6.1.1",), handler=agents.statements, run_by=CLOSERS),
    StepSpec("6.2.1", "6.2.1", "Review", PERSON, (
        L5Spec("6.2.1.a", "Accruals and exceptions", Review),
    ), capacity=Cap.CONTROLLER.value, after=("6.1.2", "6.1.3")),
    StepSpec("6.2.2", "6.2.2", "Sign off", PERSON, (
        L5Spec("6.2.2.a", "Approve; evidence auto-filed", SignOff),
    ), capacity=Cap.CONTROLLER.value, after=("6.2.1",), distinct_from=(OWNER,)),
)  # fmt: skip

RULES = (
    Rule("AP6.R1", "Accruals posted by close deadline",
         enforced_by="a daily job checks each close against the policy's close day of the "
                     "next month and raises a finding when it isn't signed off or its accrual "
                     "isn't in the ledger"),
    Rule("AP6.R2", "Reconciliation signed every month", check=service.explained_rule,
         enforced_by="one close per entity and month; it completes only when the controller "
                     "signs off (6.2.2), and an unexplained difference needs their comment"),
    Rule("AP6.R3", "Evidence kept for auditors",
         enforced_by="sign-off files an evidence pack on the case: every step result, the "
                     "review, the audit trail and a SHA-256 manifest"),
    Rule("AP6.G1", "Agent proposes; controller posts",
         enforced_by="the accrual and its reversal are proposed posting tasks only the "
                     "controller posts; a fresh snapshot verifies them"),
    Rule("AP6.G2", "Full audit trail",
         enforced_by="every step, sign-off and posting is an audit event in the hash chain, "
                     "and the evidence pack carries it"),
    Rule("AP6.P1", "Spreadsheets rebuilt every month",
         enforced_by="6.1.1 and 6.1.2 compute the accrual and reconciliation from the ERP "
                     "snapshot: nothing is rebuilt by hand"),
    Rule("AP6.P2", "Late adjustments delay close",
         enforced_by="the reconciliation runs daily on the newest snapshot, so a late posting "
                     "shows as a finding before the close, not after"),
    Rule("AP6.P3", "Audit evidence hard to assemble",
         enforced_by="the evidence pack is filed automatically on sign-off (AP6.R3)"),
)  # fmt: skip

SPEC = WorkflowSpec(
    key=WorkflowKey.AP_MONTH_CLOSE,
    name="AP Month-End Close",
    prefix="APC",
    description=(
        "A month's AP close: receipts not invoiced accrued, the payables subledger reconciled "
        "to the ledger, vendor statements read; the controller reviews and signs off, the "
        "evidence is filed and the accruals posted."
    ),
    required=frozenset(
        {
            Collection.ITEMS,
            Collection.VENDORS,
            Collection.PURCHASE_ORDERS,
            Collection.PURCHASE_RECEIPTS,
            Collection.BILLS,
            Collection.LEDGER_BALANCES,
            Collection.LEDGER_ENTRIES,
        }
    ),
    signoffs=(),
    pod=PodKey.FINANCE,
    plan=StepPlan(
        steps=STEPS,
        rules=RULES,
        measures=(
            Measure("AP6.M1", "Days to close", "days", service.days_to_close),
            Measure("AP6.M2", "Reconciling items", "count", service.reconciling_items),
            Measure("AP6.M3", "Audit findings", "count", service.audit_findings),
        ),
        viewers=CLOSERS,
        openers=CLOSERS,
        on_release=service.on_sign_off,
        posters={"create_journal_entry": frozenset({Cap.CONTROLLER.value})},
    ),
)
