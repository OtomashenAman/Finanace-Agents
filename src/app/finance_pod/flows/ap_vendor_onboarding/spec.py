"""AP-1 L3 1.5 Onboard new vendor (GIA drill-down page 4), opened from a purchase request
when the buyer chooses a vendor that isn't in the master (or by AP directly)."""

from src.app.finance_pod.capacities import FinanceCapacity as Cap
from src.app.finance_pod.flows.ap_vendor_onboarding import agents, service
from src.app.finance_pod.flows.ap_vendor_onboarding.results import (
    Activation,
    CallBack,
    DocumentsRead,
    Invitation,
    Validation,
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
AP = frozenset({Cap.AP_ANALYST.value, Cap.BUYER.value})

STEPS = (
    StepSpec("1.5.1.a", "1.5.1", "Onboarding agent: portal link", AGENT, (
        L5Spec("1.5.1.a", "Sends secure portal link", Invitation),
    ), handler=agents.send_invitation, run_by=AP),
    StepSpec("1.5.1.b", "1.5.1", "Onboarding agent: reads documents", AGENT, (
        L5Spec("1.5.1.b", "Reads tax form and bank letter", DocumentsRead),
    ), after=("1.5.1.a",), handler=agents.read_documents, run_by=AP),
    StepSpec("1.5.1.c", "1.5.1", "Onboarding agent: validates", AGENT, (
        L5Spec("1.5.1.c", "Validates tax ID; sanctions screen", Validation),
    ), after=("1.5.1.b",), handler=agents.validate, run_by=AP),
    StepSpec("1.5.2.a", "1.5.2", "AP analyst verifies the bank", PERSON, (
        L5Spec("1.5.2.a", "Calls back to confirm bank", CallBack),
    ), capacity=Cap.AP_ANALYST.value, after=("1.5.1.c",), on_done=service.after_call_back),
    StepSpec("1.5.2.b", "1.5.2", "Second approver activates", PERSON, (
        L5Spec("1.5.2.b", "Second approver activates vendor", Activation),
    ), capacity=Cap.VENDOR_APPROVER.value, after=("1.5.2.a",),
       distinct_from=(OWNER, "1.5.2.a")),
)  # fmt: skip

RULES = (
    Rule("AP1.R3", "New vendors need two-person approval",
         enforced_by="1.5.2.b must be someone other than the case owner and the AP analyst "
                     "who made the call-back"),
    Rule("AP1.G2", "Bank changes never accepted by email", check=service.bank_from_portal_rule,
         enforced_by="bank details only from portal uploads; a reply carrying bank details "
                     "raises a blocking review task"),
    Rule("AP1.P3", "Bank details sent by email: fraud risk",
         enforced_by="the portal link and AP1.G2; the invitation tells the vendor not to email "
                     "bank details"),
)  # fmt: skip

SPEC = WorkflowSpec(
    key=WorkflowKey.AP_VENDOR_ONBOARDING,
    name="Vendor Onboarding",
    prefix="VND",
    description=(
        "A new vendor through the secure portal: tax form and bank letter read and checked, "
        "sanctions screened, the bank confirmed by phone, a second person activates it, and "
        "the supplier goes to ERPNext."
    ),
    required=frozenset({Collection.VENDORS}),
    signoffs=(),
    pod=PodKey.FINANCE,
    plan=StepPlan(
        steps=STEPS,
        rules=RULES,
        measures=(Measure("AP1.M3", "Vendor set-up time", "days", service.setup_time),),
        viewers=frozenset({Cap.AP_ANALYST.value, Cap.VENDOR_APPROVER.value, Cap.BUYER.value}),
        openers=frozenset({Cap.AP_ANALYST.value, Cap.BUYER.value}),
        on_release=service.create_supplier,
        senders={"vendor_invite": frozenset({Cap.AP_ANALYST.value, Cap.BUYER.value})},
        posters={"create_supplier": frozenset({Cap.VENDOR_APPROVER.value, Cap.AP_ANALYST.value})},
    ),
)
