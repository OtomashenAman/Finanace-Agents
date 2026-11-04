from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.BANK_RECON,
    name="Bank-to-Invoice Reconciliation",
    prefix="BNK",
    description=(
        "Cleared bank receipts allocated to invoices on customer instructions, posted "
        "manually and verified against a fresh export."
    ),
    required=frozenset(
        {Collection.CUSTOMERS, Collection.INVOICES, Collection.PAYMENTS, Collection.BANK_RECEIPTS}
    ),
)
