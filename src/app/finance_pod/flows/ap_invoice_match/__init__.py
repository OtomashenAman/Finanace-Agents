"""AP-3 Invoice Processing & Matching (Finance POD).

The posting agent takes the incoming invoice (an ERPNext draft) from validated data with its
source document and guards against duplicates; the match agent matches each line to its PO
and receipts within GIA's tolerances and routes it: matched, to coding (AP-4); a variance,
to an exception the buyer decides (accept, credit, amend the PO) and the agent re-matches;
a missing receipt, to the receivers, whose confirmation posts the receipt in ERPNext.

    spec.py     the steps, rules, measures
    results.py  what each L5 step records
    policy.py   tolerances (demo values until GIA's)
    agents.py   the AGENT steps (matching is pure code)
    service.py  opening, the receipt posting, rules, measures, the weekly review
    router.py   /finance/apm/intake: a case for every new incoming invoice
"""

from src.app.finance_pod.flows.ap_invoice_match import service
from src.app.finance_pod.flows.ap_invoice_match.router import router
from src.app.finance_pod.flows.ap_invoice_match.spec import SPEC
from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register

register(
    SPEC,
    WorkflowHooks(on_create=service.on_create, purposes={"invoice_query": "Invoice query"}),
    router,
)
