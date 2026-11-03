"""Accounts Receivable (Order-to-Cash), transcribed from GIA_AP_AR_L4_L5_Drilldown.pdf.

Word for word from the slides; codes as printed (they restart at 1.1 for AR, so a code is
unique within its process, not across AP and AR). Phases 1, 3 and 5 are the scope; their
`workflows` are filled in as each is built, and the coverage test then holds it.

GIA's lab system isn't connected yet: a lab submission is read from the ERP's sales order,
its report-issued event from the order's "report issued on" date.
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
PROCESS = "Order-to-Cash (Accounts Receivable, Lab Services)"

AR1 = Phase(
    id="AR1",
    process=PROCESS,
    title="Client Account & Credit Set-Up",
    pages="15-16",
    activities=(
        L3("1.1", "Client onboarding", "Onboarding agent + client", "Client portal", (
            L4("1.1.1", "Client applies", PERSON, (
                ("1.1.1.a", "Completes portal form"),
                ("1.1.1.b", "Uploads documents"),
            )),
            L4("1.1.2", "Onboarding agent", AGENT, (
                ("1.1.2.a", "Reads and validates documents"),
                ("1.1.2.b", "Runs compliance screening"),
                ("1.1.2.c", "Flags gaps to client"),
            )),
        )),
        L3("1.2", "Credit decision", "Credit agent + credit controller", "Credit data, ERP", (
            L4("1.2.1", "Credit agent", AGENT, (
                ("1.2.1.a", "Scores risk from data"),
                ("1.2.1.b", "Proposes limit or deposit"),
            )),
            L4("1.2.2", "Credit controller", PERSON, (
                ("1.2.2.a", "Approves terms and limit"),
            )),
        )),
        L3("1.3", "Create account", "Account agent", "ERP, lab system", (
            L4("1.3.1", "Set up once", AGENT, (
                ("1.3.1.a", "Creates client in both systems"),
                ("1.3.1.b", "Keeps them in sync"),
            )),
            L4("1.3.2", "Monitor", AGENT, (
                ("1.3.2.a", "Reviews limits as history builds"),
            )),
        )),
    ),
    items=(
        Item("AR1.R1", RULE, "Credit limits approved by finance"),
        Item("AR1.R2", RULE, "New clients may start on deposit"),
        Item("AR1.R3", RULE, "Accounts reviewed periodically"),
        Item("AR1.G1", GUARDRAIL, "No credit without human approval"),
        Item("AR1.P1", PAIN, "Set-up done twice: ERP and lab system"),
        Item("AR1.P2", PAIN, "Limits rarely reviewed"),
        Item("AR1.P3", PAIN, "Documents held in email"),
    ),
    checkpoints=(
        Checkpoint("Credit controller approves terms", Cap.CREDIT_CONTROLLER),
    ),
    measures=(
        MeasureReq("AR1.M1", "Account set-up time"),
        MeasureReq("AR1.M2", "Data errors"),
    ),
    workflows=("ar_client_account",),
)  # fmt: skip

AR3 = Phase(
    id="AR3",
    process=PROCESS,
    title="Billing & Invoicing",
    pages="19-20",
    activities=(
        L3("3.1", "Build the invoice", "Billing agent", "Lab system, ERP", (
            L4("3.1.1", "Trigger", AGENT, (
                ("3.1.1.a", "On report-issued event"),
            )),
            L4("3.1.2", "Build", AGENT, (
                ("3.1.2.a", "Services actually performed"),
                ("3.1.2.b", "Client and account terms"),
            )),
        )),
        L3("3.2", "Price and check", "Fee-rule agent", "Fee schedule", (
            L4("3.2.1", "Apply rules", AGENT, (
                ("3.2.1.a", "Fees, discounts, contract prices"),
                ("3.2.1.b", "Currency and tax"),
            )),
            L4("3.2.2", "Check", AGENT, (
                ("3.2.2.a", "Compare to fee estimate"),
                ("3.2.2.b", "Flag unusual items"),
            )),
        )),
        L3("3.3", "Exceptions", "Billing analyst", "Review queue", (
            L4("3.3.1", "Billing analyst", PERSON, (
                ("3.3.1.a", "Reviews flagged invoices"),
                ("3.3.1.b", "Approves price overrides"),
            )),
        )),
        L3("3.5", "Deliver", "Delivery agent", "ERP, portal, email", (
            L4("3.5.1", "Send", AGENT, (
                ("3.5.1.a", "Posts invoice; portal and email"),
                ("3.5.1.b", "Monthly statements automatic"),
            )),
        )),
    ),
    items=(
        Item("AR3.R1", RULE, "Invoice every completed submission"),
        Item("AR3.R2", RULE, "Fees per published schedule or contract"),
        Item("AR3.R3", RULE, "Tax by client location"),
        Item("AR3.G1", GUARDRAIL, "Agent never changes fee schedule"),
        Item("AR3.P1", PAIN, "Double entry from lab to ERP"),
        Item("AR3.P2", PAIN, "Fee questions settled by email"),
        Item("AR3.P3", PAIN, "Invoices sent one by one"),
    ),
    checkpoints=(
        Checkpoint("Billing analyst approves overrides", Cap.BILLING_ANALYST),
    ),
    measures=(
        MeasureReq("AR3.M1", "Billing accuracy"),
        MeasureReq("AR3.M2", "Days to invoice"),
    ),
    workflows=("ar_billing",),
)  # fmt: skip

AR5 = Phase(
    id="AR5",
    process=PROCESS,
    title="Collections & Credit Holds",
    pages="23-24",
    activities=(
        L3("5.1", "Prioritise", "Collections agent", "ERP", (
            L4("5.1.1", "Score risk", AGENT, (
                ("5.1.1.a", "Age, amount, history, behaviour"),
            )),
            L4("5.1.2", "Plan", AGENT, (
                ("5.1.2.a", "Next action per account"),
            )),
        )),
        L3("5.2", "Follow up", "Collections agent", "Email, portal", (
            L4("5.2.1", "Tailored reminders", AGENT, (
                ("5.2.1.a", "Right tone and timing"),
                ("5.2.1.b", "Pay links in portal"),
            )),
            L4("5.2.2", "Track promises", AGENT, (
                ("5.2.2.a", "Follows up automatically"),
            )),
        )),
        L3("5.3", "Key accounts and holds", "Credit controller", "Workflow, phone", (
            L4("5.3.1", "Credit controller", PERSON, (
                ("5.3.1.a", "Calls key clients"),
                ("5.3.1.b", "Agrees plans"),
                ("5.3.1.c", "Decides holds"),
            )),
        )),
    ),
    items=(
        Item("AR5.R1", RULE, "Reminder stages by days overdue"),
        Item("AR5.R2", RULE, "Holds approved by finance"),
        Item("AR5.R3", RULE, "Key accounts handled personally"),
        Item("AR5.G1", GUARDRAIL, "No hold without human decision"),
        Item("AR5.P1", PAIN, "Lists rebuilt each cycle"),
        Item("AR5.P2", PAIN, "Reminders not tailored"),
        Item("AR5.P3", PAIN, "Holds applied inconsistently"),
    ),
    checkpoints=(
        Checkpoint("Credit controller decides holds and plans", Cap.CREDIT_CONTROLLER),
    ),
    measures=(
        MeasureReq("AR5.M1", "Days sales outstanding"),
        MeasureReq("AR5.M2", "Overdue balance"),
    ),
)  # fmt: skip

PHASES: tuple[Phase, ...] = (AR1, AR3, AR5)
