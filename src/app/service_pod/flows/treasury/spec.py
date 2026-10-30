from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.TREASURY,
    name="Treasury Forecast",
    prefix="TRS",
    description=(
        "A 13-week cash view from bank-verified cash, approved receipt schedules and "
        "approved outflows, with scenarios and owned mitigations."
    ),
    required=frozenset(
        {Collection.CASH_POSITION, Collection.INVOICES, Collection.PLANNED_OUTFLOWS}
    ),
)
