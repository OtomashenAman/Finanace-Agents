"""Accounts Payable (Procure-to-Pay), transcribed from GIA_AP_AR_L4_L5_Drilldown.pdf.

Word for word from the slides; codes as printed. Phases 1, 3 and 6 are the first scope;
the others are added here when their workflows are built.
"""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.requirements.model import (
    L3,
    L4,
    Checkpoint,
    Item,
    ItemKind,
    MeasureReq,
    Phase,
)
from src.app.service_pod.core.steps.spec import StepKind

AGENT, PERSON = StepKind.AGENT, StepKind.PERSON
RULE, GUARDRAIL, PAIN = ItemKind.RULE, ItemKind.GUARDRAIL, ItemKind.PAIN_POINT

AP1 = Phase(
    id="AP1",
    process="Procure-to-Pay (Accounts Payable)",
    title="Purchase Request & Purchase Order",
    pages="3-4",
    activities=(
        L3("1.1", "Capture the request", "Requester + request agent", "Request portal", (
            L4("1.1.1", "Describe the need", PERSON, (
                ("1.1.1.a", "Item, quantity, purpose in form or chat"),
                ("1.1.1.b", "Upload quote if available"),
            )),
            L4("1.1.2", "Request agent enriches", AGENT, (
                ("1.1.2.a", "Suggests cost centre, lab, grant"),
                ("1.1.2.b", "Checks catalogue and contract prices"),
                ("1.1.2.c", "Flags missing data before submit"),
            )),
        )),
        L3("1.2", "Budget check and approval", "Budget agent + budget owner",
           "Workflow, budget data", (
            L4("1.2.1", "Budget agent checks", AGENT, (
                ("1.2.1.a", "Remaining budget or grant balance"),
                ("1.2.1.b", "Grant allowability rules"),
                ("1.2.1.c", "Routes by authority matrix"),
            )),
            L4("1.2.2", "Budget owner decides", PERSON, (
                ("1.2.2.a", "Sees budget impact on screen"),
                ("1.2.2.b", "Approves, rejects or queries"),
            )),
        )),
        L3("1.3", "Select vendor", "Sourcing agent + buyer", "Vendor master, contracts", (
            L4("1.3.1", "Sourcing agent", AGENT, (
                ("1.3.1.a", "Finds approved vendors and contracts"),
                ("1.3.1.b", "Requests quotes above threshold"),
                ("1.3.1.c", "Compares quotes side by side"),
            )),
            L4("1.3.2", "Buyer chooses", PERSON, (
                ("1.3.2.a", "Reviews comparison"),
                ("1.3.2.b", "Confirms vendor and terms"),
            )),
        )),
        L3("1.5", "Onboard new vendor", "Onboarding agent + AP analyst", "Vendor portal, ERP", (
            L4("1.5.1", "Onboarding agent", AGENT, (
                ("1.5.1.a", "Sends secure portal link"),
                ("1.5.1.b", "Reads tax form and bank letter"),
                ("1.5.1.c", "Validates tax ID; sanctions screen"),
            )),
            L4("1.5.2", "AP analyst verifies", PERSON, (
                ("1.5.2.a", "Calls back to confirm bank"),
                ("1.5.2.b", "Second approver activates vendor"),
            )),
        )),
        L3("1.6", "Create and issue PO", "PO agent + buyer", "ERP", (
            L4("1.6.1", "PO agent", AGENT, (
                ("1.6.1.a", "Drafts PO from approved request"),
                ("1.6.1.b", "Applies coding and terms"),
                ("1.6.1.c", "Sends PO; logs acknowledgement"),
            )),
            L4("1.6.2", "Buyer approves", PERSON, (
                ("1.6.2.a", "Approves POs above limit"),
            )),
        )),
    ),
    items=(
        Item("AP1.R1", RULE, "Quotes required above purchasing threshold"),
        Item("AP1.R2", RULE, "Requester cannot approve own request"),
        Item("AP1.R3", RULE, "New vendors need two-person approval"),
        Item("AP1.R4", RULE, "New vendor? If new: request set-up from AP; if existing: go to PO"),
        Item("AP1.G1", GUARDRAIL, "No PO without approved request"),
        Item("AP1.G2", GUARDRAIL, "Bank changes never accepted by email"),
        Item("AP1.P1", PAIN, "Requests without budget codes"),
        Item("AP1.P2", PAIN, "Urgent buys made before a PO exists"),
        Item("AP1.P3", PAIN, "Bank details sent by email: fraud risk"),
        Item("AP1.P4", PAIN, "No tracking of request status"),
    ),
    checkpoints=(
        Checkpoint("Budget owner approval", Cap.BUDGET_OWNER),
        Checkpoint("Buyer vendor choice", Cap.BUYER),
        Checkpoint("Bank call-back", Cap.AP_ANALYST),
        Checkpoint("Second approval", Cap.VENDOR_APPROVER),
    ),
    measures=(
        MeasureReq("AP1.M1", "Request-to-PO cycle time"),
        MeasureReq("AP1.M2", "Requests needing rework"),
        MeasureReq("AP1.M3", "Vendor set-up time"),
    ),
    workflows=("ap_purchase_request", "ap_vendor_onboarding"),
)  # fmt: skip

AP3 = Phase(
    id="AP3",
    process="Procure-to-Pay (Accounts Payable)",
    title="Invoice Processing & Matching",
    pages="7-8",
    activities=(
        L3("3.2", "Post the invoice", "Posting agent", "ERP", (
            L4("3.2.1", "Create invoice in ERP", AGENT, (
                ("3.2.1.a", "From validated data"),
                ("3.2.1.b", "Attach source document"),
            )),
            L4("3.2.2", "Duplicate guard", AGENT, (
                ("3.2.2.a", "Fuzzy match on number, amount"),
                ("3.2.2.b", "Blocks and explains"),
            )),
        )),
        L3("3.4", "Match", "Match agent", "ERP", (
            L4("3.4.1", "Three-way match", AGENT, (
                ("3.4.1.a", "Line by line vs PO and receipt"),
                ("3.4.1.b", "Applies GIA tolerances"),
            )),
            L4("3.4.2", "Classify outcome", AGENT, (
                ("3.4.2.a", "Match: send to coding"),
                ("3.4.2.b", "Variance: open exception"),
            )),
        )),
        L3("3.5", "Resolve variances", "Exception agent + buyer", "Workflow", (
            L4("3.5.1", "Prepare the case", AGENT, (
                ("3.5.1.a", "Shows PO, receipt, invoice"),
                ("3.5.1.b", "Drafts vendor query"),
            )),
            L4("3.5.2", "Buyer decides", PERSON, (
                ("3.5.2.a", "Accept, credit or amend PO"),
            )),
            L4("3.5.3", "Close the loop", AGENT, (
                ("3.5.3.a", "Re-matches; releases invoice"),
            )),
        )),
        L3("3.6", "Chase missing receipts", "Receipt agent + receiver", "Mobile", (
            L4("3.6.1", "Nudge receiver", AGENT, (
                ("3.6.1.a", "Requests confirmation"),
            )),
            L4("3.6.2", "Receiver confirms", PERSON, (
                ("3.6.2.a", "Posts receipt on mobile"),
            )),
        )),
    ),
    items=(
        Item("AP3.R1", RULE, "Price and quantity tolerances apply per line"),
        Item("AP3.R2", RULE, "Duplicates blocked by number, vendor, amount"),
        Item("AP3.R3", RULE, "Held invoices reviewed weekly"),
        Item("AP3.G1", GUARDRAIL, "Agent never changes PO prices"),
        Item("AP3.G2", GUARDRAIL, "All decisions logged"),
        Item("AP3.P1", PAIN, "Keying is the largest effort in AP"),
        Item("AP3.P2", PAIN, "Variances resolved by email, slowly"),
        Item("AP3.P3", PAIN, "Held invoices age without owners"),
    ),
    checkpoints=(
        Checkpoint("Buyer decides on variances", Cap.BUYER),
        Checkpoint("Receiver confirms missing receipts", Cap.RECEIVER),
    ),
    measures=(
        MeasureReq("AP3.M1", "First-pass match rate"),
        MeasureReq("AP3.M2", "Exception ageing"),
        MeasureReq("AP3.M3", "Duplicates stopped"),
    ),
    workflows=("ap_invoice_match",),
)  # fmt: skip

AP6 = Phase(
    id="AP6",
    process="Procure-to-Pay (Accounts Payable)",
    title="Month-End Close",
    pages="13-14",
    activities=(
        L3("6.1", "Prepare close", "Close agent", "ERP", (
            L4("6.1.1", "Accruals", AGENT, (
                ("6.1.1.a", "Lists receipts not invoiced"),
                ("6.1.1.b", "Proposes accrual journal"),
            )),
            L4("6.1.2", "Reconcile", AGENT, (
                ("6.1.2.a", "Subledger vs ledger daily"),
                ("6.1.2.b", "Explains differences"),
            )),
            L4("6.1.3", "Vendor statements", AGENT, (
                ("6.1.3.a", "Reads statements; flags gaps"),
            )),
        )),
        L3("6.2", "Review and sign off", "Controller", "ERP, close tracker", (
            L4("6.2.1", "Review", PERSON, (
                ("6.2.1.a", "Accruals and exceptions"),
            )),
            L4("6.2.2", "Sign off", PERSON, (
                ("6.2.2.a", "Approve; evidence auto-filed"),
            )),
        )),
    ),
    items=(
        Item("AP6.R1", RULE, "Accruals posted by close deadline"),
        Item("AP6.R2", RULE, "Reconciliation signed every month"),
        Item("AP6.R3", RULE, "Evidence kept for auditors"),
        Item("AP6.G1", GUARDRAIL, "Agent proposes; controller posts"),
        Item("AP6.G2", GUARDRAIL, "Full audit trail"),
        Item("AP6.P1", PAIN, "Spreadsheets rebuilt every month"),
        Item("AP6.P2", PAIN, "Late adjustments delay close"),
        Item("AP6.P3", PAIN, "Audit evidence hard to assemble"),
    ),
    checkpoints=(Checkpoint("Controller reviews and signs off", Cap.CONTROLLER),),
    measures=(
        MeasureReq("AP6.M1", "Days to close"),
        MeasureReq("AP6.M2", "Reconciling items"),
        MeasureReq("AP6.M3", "Audit findings"),
    ),
)  # fmt: skip

PHASES = (AP1, AP3, AP6)
