"""AR-3 Billing & Invoicing (GIA drill-down page 20)."""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.flows.ar_billing import agents, service
from src.app.finance_pod.flows.ar_billing.results import (
    AccountTerms,
    Delivered,
    EstimateCheck,
    Flags,
    FlagsReviewed,
    OnStatement,
    Overrides,
    Performed,
    Priced,
    Taxed,
    Triggered,
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
BILLING = Cap.BILLING_ANALYST.value
DESK = frozenset({BILLING, Cap.CREDIT_CONTROLLER.value})

STEPS = (
    StepSpec("3.1.1", "3.1.1", "Trigger", AGENT, (
        L5Spec("3.1.1.a", "On report-issued event", Triggered),
    ), handler=agents.trigger, run_by=DESK),
    StepSpec("3.1.2", "3.1.2", "Build", AGENT, (
        L5Spec("3.1.2.a", "Services actually performed", Performed),
        L5Spec("3.1.2.b", "Client and account terms", AccountTerms),
    ), after=("3.1.1",), handler=agents.build, run_by=DESK),
    StepSpec("3.2.1", "3.2.1", "Apply rules", AGENT, (
        L5Spec("3.2.1.a", "Fees, discounts, contract prices", Priced),
        L5Spec("3.2.1.b", "Currency and tax", Taxed),
    ), after=("3.1.2",), handler=agents.apply_rules, run_by=DESK),
    StepSpec("3.2.2", "3.2.2", "Check", AGENT, (
        L5Spec("3.2.2.a", "Compare to fee estimate", EstimateCheck),
        L5Spec("3.2.2.b", "Flag unusual items", Flags),
    ), after=("3.2.1",), handler=agents.check, run_by=DESK),
    StepSpec("3.3.1", "3.3.1", "Billing analyst", PERSON, (
        L5Spec("3.3.1.a", "Reviews flagged invoices", FlagsReviewed),
        L5Spec("3.3.1.b", "Approves price overrides", Overrides),
    ), capacity=BILLING, after=("3.2.2",), not_applicable_when=agents.no_flags,
       on_done=service.after_review),
    # After the release: the invoice in the ERP and to the client, then on a statement
    StepSpec("3.5.1.a", "3.5.1", "Send: invoice", AGENT, (
        L5Spec("3.5.1.a", "Posts invoice; portal and email", Delivered),
    ), after=("3.3.1",), handler=agents.send, run_by=DESK, after_approval=True),
    StepSpec("3.5.1.b", "3.5.1", "Send: statement", AGENT, (
        L5Spec("3.5.1.b", "Monthly statements automatic", OnStatement),
    ), after=("3.5.1.a",), handler=service.statement_sent, run_by=DESK, after_approval=True),
)  # fmt: skip

RULES = (
    Rule("AR3.R1", "Invoice every completed submission",
         enforced_by="Take in opens a billing case for every submission whose report is "
                     "issued and isn't billed (one case each; a submission still in the lab "
                     "isn't billable)"),
    Rule("AR3.R2", "Fees per published schedule or contract", check=service.schedule_rule,
         enforced_by="3.2.1 prices each line from the schedule, the client's own price or a "
                     "pricing rule; anything else is a billing analyst's override"),
    Rule("AR3.R3", "Tax by client location",
         enforced_by="3.2.1.b takes the sales tax template of the client's tax category "
                     "(domestic, export)"),
    Rule("AR3.G1", "Agent never changes fee schedule",
         enforced_by="no posting touches a price list or pricing rule; an override applies to "
                     "its invoice only"),
    Rule("AR3.P1", "Double entry from lab to ERP",
         enforced_by="the invoice is built from the submission's own lines and posted by the "
                     "app, linked to them"),
    Rule("AR3.P2", "Fee questions settled by email",
         enforced_by="3.2.2 flags what differs from the estimate or schedule; 3.3.1 settles it "
                     "in the case, with the reason recorded"),
    Rule("AR3.P3", "Invoices sent one by one",
         enforced_by="each invoice is drafted for sending as it's posted, and the month's "
                     "statements go out in one batch"),
)  # fmt: skip

SPEC = WorkflowSpec(
    key=WorkflowKey.AR_BILLING,
    name="Billing & Invoicing",
    prefix="BIL",
    description=(
        "One case per lab submission whose report is issued: the services performed, priced "
        "by the fee schedule, the client's price or contract discount, taxed by location, "
        "checked against the fee estimate; a billing analyst settles what's flagged; the "
        "invoice goes to ERPNext and the client, and onto the monthly statement."
    ),
    required=frozenset(
        {
            Collection.CLIENTS,
            Collection.SUBMISSIONS,
            Collection.SELLING_PRICES,
            Collection.TAX_RULES,
        }
    ),
    signoffs=(),
    pod=PodKey.FINANCE,
    plan=StepPlan(
        steps=STEPS,
        rules=RULES,
        measures=(
            Measure("AR3.M1", "Billing accuracy", "%", service.accuracy),
            Measure("AR3.M2", "Days to invoice", "days", service.days_to_invoice),
        ),
        viewers=DESK,
        openers=DESK,
        on_release=service.create_invoice,
        senders={"client_invoice": DESK, "client_statement": frozenset({BILLING})},
        posters={"create_sales_invoice": frozenset({BILLING})},
    ),
)
