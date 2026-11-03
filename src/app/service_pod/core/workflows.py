"""What every POD workflow declares: its POD, key, name and the source data it needs.

Two PODs share the one case engine: the Service POD (Finance Admin only, one person runs
every step) and the Finance POD (multi-user: capacities, L4/L5 steps, segregation of
duties). The specs live with each workflow (service_pod/flows/<workflow>/spec.py and
finance_pod/flows/<workflow>/spec.py) and are added to WORKFLOWS by core.registry when the
flow packages are imported.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.steps.spec import StepPlan

RELEASED = "released"  # the approval capacity of a release (no sign-off)


class PodKey(StrEnum):
    SERVICE = "service"
    FINANCE = "finance"


class WorkflowKey(StrEnum):
    AR_COLLECTIONS = "ar_collections"
    BANK_RECON = "bank_recon"
    FPA_TREND = "fpa_trend"
    TREASURY = "treasury"
    REPORTING = "reporting"
    # Finance POD: Procure-to-Pay
    AP_PURCHASE_REQUEST = "ap_purchase_request"
    AP_VENDOR_ONBOARDING = "ap_vendor_onboarding"
    AP_INVOICE_MATCH = "ap_invoice_match"
    AP_MONTH_CLOSE = "ap_month_close"
    # Finance POD: Order-to-Cash
    AR_CLIENT_ACCOUNT = "ar_client_account"


@dataclass(frozen=True)
class WorkflowSpec:
    key: WorkflowKey
    name: str
    prefix: str  # case references: AR-0042
    description: str
    required: frozenset[Collection]  # a case can't start on a snapshot without these
    # The sign-offs a case needs, in order, each recorded in its capacity (deck: Finance Head
    # for FP&A; Controller then CFO for Reporting). In the Service POD the Finance Admin gives
    # every sign-off; in the Finance POD each needs a person holding that capacity.
    signoffs: tuple[str, ...] = ("Finance Admin",)
    pod: PodKey = PodKey.SERVICE
    # Finance POD: the requirement's L4/L5 steps, rules and measures
    plan: StepPlan = field(default_factory=StepPlan)
    # Every sign-off from someone other than the case's owner and the earlier sign-offs
    signoff_sod: bool = False

    @property
    def released(self) -> bool:
        """Finance POD workflows without sign-offs are released (approved) by the engine as
        soon as every step before approval is settled and nothing blocks: the checkpoints
        are the people's own steps."""
        return not self.signoffs

    @property
    def signoff_as(self) -> str:
        """The first (usually only) sign-off's capacity."""
        return self.signoffs[0] if self.signoffs else RELEASED


# Filled by core.registry.register() as each flow package is imported (in import order)
WORKFLOWS: dict[WorkflowKey, WorkflowSpec] = {}


def workflows_in(pod: PodKey) -> list[WorkflowSpec]:
    return [spec for spec in WORKFLOWS.values() if spec.pod == pod]


def keys_in(pod: PodKey) -> list[WorkflowKey]:
    return [spec.key for spec in workflows_in(pod)]
