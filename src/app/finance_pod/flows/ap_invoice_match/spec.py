"""AP-3 Invoice Processing & Matching (GIA drill-down pages 7-8): L3 3.2, 3.4, 3.5 and 3.6,
one case per incoming supplier invoice (an ERPNext draft from intake). A matched invoice goes
on to coding and approval (AP-4); the agents never post it and never change a PO."""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.flows.ap_invoice_match import agents, service
from src.app.finance_pod.flows.ap_invoice_match.results import (
    BuyerDecision,
    DuplicateDecision,
    DuplicateSearch,
    ExceptionView,
    InvoiceRecord,
    LineByLine,
    LoopClosed,
    Nudge,
    OpenException,
    ReceiptConfirmed,
    SendToCoding,
    SourceDocument,
    Tolerances,
    VendorQuery,
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
AP = frozenset({Cap.AP_ANALYST.value})
AP_OR_BUYER = frozenset({Cap.AP_ANALYST.value, Cap.BUYER.value})

STEPS = (
    StepSpec("3.2.1", "3.2.1", "Create invoice in ERP", AGENT, (
        L5Spec("3.2.1.a", "From validated data", InvoiceRecord),
        L5Spec("3.2.1.b", "Attach source document", SourceDocument),
    ), handler=agents.validate_invoice, run_by=AP),
    StepSpec("3.2.2", "3.2.2", "Duplicate guard", AGENT, (
        L5Spec("3.2.2.a", "Fuzzy match on number, amount", DuplicateSearch),
        L5Spec("3.2.2.b", "Blocks and explains", DuplicateDecision),
    ), after=("3.2.1",), handler=agents.duplicate_guard, run_by=AP),
    StepSpec("3.4.1", "3.4.1", "Three-way match", AGENT, (
        L5Spec("3.4.1.a", "Line by line vs PO and receipt", LineByLine),
        L5Spec("3.4.1.b", "Applies GIA tolerances", Tolerances),
    ), after=("3.2.2",), handler=agents.three_way_match, run_by=AP),
    StepSpec("3.4.2", "3.4.2", "Classify outcome", AGENT, (
        L5Spec("3.4.2.a", "Match: send to coding", SendToCoding),
        L5Spec("3.4.2.b", "Variance: open exception", OpenException),
    ), after=("3.4.1",), handler=agents.classify, run_by=AP),
    StepSpec("3.5.1", "3.5.1", "Prepare the case", AGENT, (
        L5Spec("3.5.1.a", "Shows PO, receipt, invoice", ExceptionView),
        L5Spec("3.5.1.b", "Drafts vendor query", VendorQuery),
    ), after=("3.4.2",), handler=agents.prepare_exception, run_by=AP_OR_BUYER,
       not_applicable_when=agents.no_variance),
    StepSpec("3.5.2", "3.5.2", "Buyer decides", PERSON, (
        L5Spec("3.5.2.a", "Accept, credit or amend PO", BuyerDecision),
    ), capacity=Cap.BUYER.value, after=("3.5.1",), not_applicable_when=agents.no_variance),
    StepSpec("3.6.1", "3.6.1", "Nudge receiver", AGENT, (
        L5Spec("3.6.1.a", "Requests confirmation", Nudge),
    ), after=("3.4.2",), handler=agents.nudge_receiver, run_by=AP_OR_BUYER,
       not_applicable_when=agents.receipts_complete),
    StepSpec("3.6.2", "3.6.2", "Receiver confirms", PERSON, (
        L5Spec("3.6.2.a", "Posts receipt on mobile", ReceiptConfirmed),
    ), capacity=Cap.RECEIVER.value, after=("3.6.1",), on_done=service.after_receipt,
       not_applicable_when=agents.receipts_complete),
    StepSpec("3.5.3", "3.5.3", "Close the loop", AGENT, (
        L5Spec("3.5.3.a", "Re-matches; releases invoice", LoopClosed),
    ), after=("3.5.2", "3.6.2"), handler=agents.close_loop, run_by=AP_OR_BUYER,
       not_applicable_when=agents.no_exception),
)  # fmt: skip

RULES = (
    Rule("AP3.R1", "Price and quantity tolerances apply per line",
         enforced_by="3.4.1 matches each line against its PO line and receipts with the "
                     "policy's tolerances"),
    Rule("AP3.R2", "Duplicates blocked by number, vendor, amount", check=service.duplicate_rule,
         enforced_by="3.2.2 blocks a near-identical number and amount of the same vendor"),
    Rule("AP3.R3", "Held invoices reviewed weekly",
         enforced_by="a daily job raises a review task on any held invoice untouched for the "
                     "policy's days"),
    Rule("AP3.G1", "Agent never changes PO prices",
         enforced_by="no agent writes a PO; amending it is the buyer's (3.5.2), in ERPNext"),
    Rule("AP3.G2", "All decisions logged",
         enforced_by="every step, decision and posting is an audit event in the hash chain"),
    Rule("AP3.P1", "Keying is the largest effort in AP",
         enforced_by="the invoice comes from ERPNext as it arrived; nothing is keyed again"),
    Rule("AP3.P2", "Variances resolved by email, slowly",
         enforced_by="3.5.1 lays the PO, receipt and invoice side by side and drafts the "
                     "vendor query; exception ageing is measured"),
    Rule("AP3.P3", "Held invoices age without owners",
         enforced_by="each variance waits on the buyer (3.5.2), each missing receipt on the "
                     "receivers (3.6.2); the weekly review"),
)  # fmt: skip

SPEC = WorkflowSpec(
    key=WorkflowKey.AP_INVOICE_MATCH,
    name="Invoice Matching",
    prefix="APM",
    description=(
        "An incoming supplier invoice checked for duplicates and matched line by line to its "
        "PO and receipts; variances go to the buyer, missing receipts to the receiver."
    ),
    required=frozenset(
        {
            Collection.VENDORS,
            Collection.PURCHASE_ORDERS,
            Collection.PURCHASE_RECEIPTS,
            Collection.BILLS,
        }
    ),
    signoffs=(),
    pod=PodKey.FINANCE,
    plan=StepPlan(
        steps=STEPS,
        rules=RULES,
        measures=(
            Measure("AP3.M1", "First-pass match rate", "%", service.first_pass_rate),
            Measure("AP3.M2", "Exception ageing", "days", service.exception_ageing),
            Measure("AP3.M3", "Duplicates stopped", "count", service.duplicates_stopped),
        ),
        viewers=frozenset(
            {Cap.AP_ANALYST.value, Cap.BUYER.value, Cap.RECEIVER.value, Cap.CONTROLLER.value}
        ),
        openers=frozenset({Cap.AP_ANALYST.value}),
        senders={"invoice_query": AP_OR_BUYER},
        posters={"create_purchase_receipt": frozenset({Cap.RECEIVER.value, Cap.AP_ANALYST.value})},
    ),
)
