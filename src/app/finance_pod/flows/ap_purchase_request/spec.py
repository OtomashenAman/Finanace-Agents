"""AP-1 Purchase Request & Purchase Order (GIA drill-down pages 3-4): L3 1.1, 1.2, 1.3 and
1.6, in the requirement's words. Vendor onboarding (L3 1.5) is its own workflow, opened from
step 1.3.2 when the buyer chooses a new vendor (AP1.R4)."""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.flows.ap_purchase_request import agents, service
from src.app.finance_pod.flows.ap_purchase_request.results import (
    BudgetCheck,
    BudgetDecision,
    Coding,
    Comparison,
    ComparisonReviewed,
    DraftPo,
    GrantCheck,
    ImpactReviewed,
    MissingData,
    Need,
    PoApproval,
    PoCoding,
    PoSent,
    PriceCheck,
    QuoteRequests,
    QuoteUpload,
    Routing,
    Sourcing,
    VendorChoice,
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
BUYER = frozenset({Cap.BUYER.value})
REQUESTER = ("1.1.1",)  # SoD: the requester never approves their own request (AP1.R2)

STEPS = (
    StepSpec("1.1.1", "1.1.1", "Describe the need", PERSON, (
        L5Spec("1.1.1.a", "Item, quantity, purpose in form or chat", Need),
        L5Spec("1.1.1.b", "Upload quote if available", QuoteUpload),
    ), capacity=Cap.REQUESTER.value, on_done=service.after_need),
    StepSpec("1.1.2", "1.1.2", "Request agent enriches", AGENT, (
        L5Spec("1.1.2.a", "Suggests cost centre, lab, grant", Coding),
        L5Spec("1.1.2.b", "Checks catalogue and contract prices", PriceCheck),
        L5Spec("1.1.2.c", "Flags missing data before submit", MissingData),
    ), after=("1.1.1",), handler=agents.enrich),
    StepSpec("1.2.1", "1.2.1", "Budget agent checks", AGENT, (
        L5Spec("1.2.1.a", "Remaining budget or grant balance", BudgetCheck),
        L5Spec("1.2.1.b", "Grant allowability rules", GrantCheck),
        L5Spec("1.2.1.c", "Routes by authority matrix", Routing),
    ), after=("1.1.2",), handler=agents.check_budget),
    StepSpec("1.2.2", "1.2.2", "Budget owner decides", PERSON, (
        L5Spec("1.2.2.a", "Sees budget impact on screen", ImpactReviewed),
        L5Spec("1.2.2.b", "Approves, rejects or queries", BudgetDecision),
    ), capacity=Cap.BUDGET_OWNER.value, after=("1.2.1",), distinct_from=(OWNER, *REQUESTER),
       on_done=service.after_budget_decision),
    StepSpec("1.3.1.a", "1.3.1", "Sourcing agent: finds vendors", AGENT, (
        L5Spec("1.3.1.a", "Finds approved vendors and contracts", Sourcing),
    ), after=("1.2.2",), handler=agents.find_vendors, run_by=BUYER),
    StepSpec("1.3.1.b", "1.3.1", "Sourcing agent: requests quotes", AGENT, (
        L5Spec("1.3.1.b", "Requests quotes above threshold", QuoteRequests),
    ), after=("1.3.1.a",), handler=agents.request_quotes, run_by=BUYER,
       not_applicable_when=agents.quotes_not_needed),
    StepSpec("1.3.1.c", "1.3.1", "Sourcing agent: compares quotes", AGENT, (
        L5Spec("1.3.1.c", "Compares quotes side by side", Comparison),
    ), after=("1.3.1.b",), handler=agents.compare_quotes, run_by=BUYER),
    StepSpec("1.3.2", "1.3.2", "Buyer chooses", PERSON, (
        L5Spec("1.3.2.a", "Reviews comparison", ComparisonReviewed),
        L5Spec("1.3.2.b", "Confirms vendor and terms", VendorChoice),
    ), capacity=Cap.BUYER.value, after=("1.3.1.c",), distinct_from=(OWNER, *REQUESTER),
       on_done=service.after_choice),
    StepSpec("1.6.1", "1.6.1", "PO agent: drafts the PO", AGENT, (
        L5Spec("1.6.1.a", "Drafts PO from approved request", DraftPo),
        L5Spec("1.6.1.b", "Applies coding and terms", PoCoding),
    ), after=("1.3.2",), handler=agents.draft_po, run_by=BUYER),
    StepSpec("1.6.2", "1.6.2", "Buyer approves", PERSON, (
        L5Spec("1.6.2.a", "Approves POs above limit", PoApproval),
    ), capacity=Cap.BUYER.value, after=("1.6.1",), distinct_from=(OWNER, *REQUESTER),
       not_applicable_when=agents.below_po_limit),
    # Released here (every checkpoint passed); then the PO goes out
    StepSpec("1.6.1.c", "1.6.1", "PO agent: sends the PO", AGENT, (
        L5Spec("1.6.1.c", "Sends PO; logs acknowledgement", PoSent),
    ), after=("1.6.2",), handler=agents.send_po, run_by=BUYER, after_approval=True),
)  # fmt: skip

RULES = (
    Rule("AP1.R1", "Quotes required above purchasing threshold", check=service.quotes_rule,
         enforced_by="1.3.1.b can't be skipped above the threshold; 1.3.1.c waits for enough "
                     "quotes"),
    Rule("AP1.R2", "Requester cannot approve own request",
         enforced_by="distinct_from the requester and the opener on 1.2.2, 1.3.2 and 1.6.2"),
    Rule("AP1.R4", "New vendor? If new: request set-up from AP; if existing: go to PO",
         check=service.new_vendor_rule,
         enforced_by="1.3.2 opens a vendor onboarding case; 1.6.1 waits for its supplier"),
    Rule("AP1.G1", "No PO without approved request", check=service.approved_request_rule,
         enforced_by="the PO is posted only after the release, which needs 1.2.2 approved"),
    Rule("AP1.P1", "Requests without budget codes",
         enforced_by="1.1.2.c fails while the cost centre (or the lab) is missing"),
    Rule("AP1.P2", "Urgent buys made before a PO exists",
         enforced_by="1.1.2 raises a blocking review task when the date needed has passed"),
    Rule("AP1.P4", "No tracking of request status",
         enforced_by="the request's own steps, the step it waits on and who holds it"),
)  # fmt: skip

SPEC = WorkflowSpec(
    key=WorkflowKey.AP_PURCHASE_REQUEST,
    name="Purchase Request & PO",
    prefix="PRQ",
    description=(
        "From a request to an issued PO: enrichment, budget and grant checks, the budget "
        "owner's decision, sourcing and quotes, the buyer's choice and the PO in ERPNext."
    ),
    required=frozenset(
        {
            Collection.VENDORS,
            Collection.ITEMS,
            Collection.ITEM_PRICES,
            Collection.COST_CENTRES,
            Collection.GRANTS,
            Collection.BUDGETS,
            Collection.BUDGET_ACTUALS,
            Collection.ACCOUNTS,
            Collection.PURCHASE_ORDERS,
            Collection.PURCHASE_REQUESTS,
            Collection.SUPPLIER_QUOTATIONS,
        }
    ),
    signoffs=(),  # released when the people's checkpoints pass
    pod=PodKey.FINANCE,
    plan=StepPlan(
        steps=STEPS,
        rules=RULES,
        measures=(
            Measure("AP1.M1", "Request-to-PO cycle time", "hours", service.cycle_time),
            Measure("AP1.M2", "Requests needing rework", "%", service.rework_rate),
        ),
        viewers=frozenset({Cap.BUDGET_OWNER.value, Cap.BUYER.value}),
        openers=frozenset({Cap.REQUESTER.value}),
        senders={
            "rfq": frozenset({Cap.BUYER.value}),
            "purchase_order": frozenset({Cap.BUYER.value}),
        },
        posters={"create_purchase_order": frozenset({Cap.BUYER.value})},
    ),
)
