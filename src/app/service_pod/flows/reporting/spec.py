from src.app.service_pod.core.snapshots.contract import Collection
from src.app.service_pod.core.workflows import WorkflowKey, WorkflowSpec

SPEC = WorkflowSpec(
    key=WorkflowKey.REPORTING,
    name="Financial Reporting",
    prefix="RPT",
    description=(
        "The monthly management pack: comparable statements, balance checks, cited "
        "commentary and sign-off."
    ),
    required=frozenset(
        {
            Collection.ACCOUNTS,
            Collection.GL_LINES,
            Collection.TRANSACTIONS,
            Collection.BALANCE_SHEETS,
            Collection.CLOSE_STATUS,
            Collection.INVOICES,
        }
    ),
    signoffs=("Controller", "CFO"),
)
