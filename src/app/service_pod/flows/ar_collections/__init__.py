"""AR Collections (deck slides 7-12, TDD section 6).

A case is one customer and some of their overdue invoices. Emails carry the invoices'
verified figures; the customer's reply is read into proposed commitments, disputes and
document requests, each tied to the customer's own words. A promise is never a receipt, a
missing date comes only from the customer, and the schedule is approved only when nothing is
disputed or unclear and the balances are current.

    spec.py     key, roles, source data needed
    schemas.py  case selection, AI reading, portfolio responses
    prompt.py   what the AI is told
    service.py  opening a case, approval blockers, messages
    reading.py  reply -> commitments / review tasks
    views.py    the AR portfolio
    router.py   /pod/ar/...
"""

from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register
from src.app.service_pod.flows.ar_collections.reading import extract_reply
from src.app.service_pod.flows.ar_collections.router import router
from src.app.service_pod.flows.ar_collections.service import (
    PURPOSES,
    blockers,
    compose,
    facts,
    on_create,
)
from src.app.service_pod.flows.ar_collections.spec import SPEC

register(
    SPEC,
    WorkflowHooks(
        on_create=on_create,
        blockers=blockers,
        purposes=PURPOSES,
        facts=facts,
        compose=compose,
        extract_reply=extract_reply,
    ),
    router,
)
