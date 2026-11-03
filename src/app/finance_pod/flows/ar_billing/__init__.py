"""AR-3 Billing & Invoicing (Finance POD).

A billing case per lab submission whose report is issued (GIA's lab system isn't connected:
the ERP sales order's "report issued on" date is the event). The agents build the invoice
from the services performed, price it (fee schedule, the client's own price, a contract
discount), tax it by the client's location and check it against the fee estimate; a billing
analyst settles anything flagged (overrides apply to that invoice only); the invoice is posted
to ERPNext, verified by a fresh snapshot and emailed; the month's statements go out in one
batch.

    spec.py     the steps, rules, measures
    results.py  what each L5 step records
    policy.py   estimate tolerance, unusual quantity (demo values until GIA's)
    agents.py   the AGENT steps
    service.py  opening, overrides, the ERPNext invoice, statements, rules, measures
    router.py   take in billable submissions; draft and send the month's statements
"""

from src.app.finance_pod.flows.ar_billing import service
from src.app.finance_pod.flows.ar_billing.router import router
from src.app.finance_pod.flows.ar_billing.spec import SPEC
from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register

register(
    SPEC,
    WorkflowHooks(
        on_create=service.on_create,
        purposes={"client_invoice": "Invoice", "client_statement": "Statement of account"},
    ),
    router,
)
