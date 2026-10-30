from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import Capacity, WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.TREASURY,
    name="Treasury Forecast",
    prefix="TRS",
    description=(
        "A 13-week cash view from bank-verified cash, approved receipt schedules and "
        "approved outflows, with scenarios and owned mitigations."
    ),
    labels={
        Capacity.PREPARER: "Treasury Analyst",
        Capacity.REVIEWER: "Treasury Head",
        Capacity.FINAL_APPROVER: "CFO",
    },
    required=frozenset(
        {Collection.CASH_POSITION, Collection.INVOICES, Collection.PLANNED_OUTFLOWS}
    ),
    visible=frozenset(
        {
            Collection.CASH_POSITION,
            Collection.INVOICES,
            Collection.CUSTOMERS,
            Collection.CONTRACTS,
            Collection.PLANNED_OUTFLOWS,
            Collection.BANK_RECEIPTS,
        }
    ),
    final_gate=True,
)
