"""Bank-to-Invoice reconciliation (deck slides 15-18, TDD section 7).

A case is one cleared bank receipt and the customer who paid it. A matching amount never
decides the allocation: the customer says which invoices it covers, in their own words, and
the lines must add up to the receipt exactly. The Finance Admin posts the Receive Payment in
QuickBooks; a fresh export must then show the payment, its allocations and the invoices'
remaining balances before the customer gets a confirmation.

    spec.py          key, roles, source data needed
    schemas.py       case selection, allocation, AI reading, worklist responses
    prompt.py        what the AI is told
    service.py       opening a case, the allocation rules, approval blockers, messages
    actions.py       record the allocation by hand, queue the posting
    reading.py       reply -> allocation
    verification.py  the posting against a fresh export
    views.py         unapplied cash
    router.py        /pod/bank/...
"""

from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register
from src.app.service_pod.flows.bank_recon.actions import ACTIONS
from src.app.service_pod.flows.bank_recon.reading import extract_reply
from src.app.service_pod.flows.bank_recon.router import router
from src.app.service_pod.flows.bank_recon.service import (
    PURPOSES,
    blockers,
    compose,
    draft_blocker,
    facts,
    on_create,
)
from src.app.service_pod.flows.bank_recon.spec import SPEC
from src.app.service_pod.flows.bank_recon.verification import verify_posting

register(
    SPEC,
    WorkflowHooks(
        actions=ACTIONS,
        on_create=on_create,
        blockers=blockers,
        purposes=PURPOSES,
        facts=facts,
        draft_blocker=draft_blocker,
        compose=compose,
        extract_reply=extract_reply,
        verify_posting=verify_posting,
    ),
    router,
)
