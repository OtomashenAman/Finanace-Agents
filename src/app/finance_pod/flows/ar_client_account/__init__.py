"""AR-1 Client Account & Credit Set-Up (Finance POD).

A credit controller (or billing analyst) opens the case and invites the client; the client
applies through a signed portal link (form and documents); the onboarding agent reads the tax
form, screens the names against the OFAC SDN list and sends any gaps back to the client; the
credit agent scores the risk and proposes a limit or a deposit; the credit controller decides;
the client is created in ERPNext with exactly those terms, verified by a fresh snapshot, and
its limit is reviewed daily as history builds.

    spec.py     the steps, rules, measures
    results.py  what each L5 step records
    policy.py   risk bands, limits, terms, review triggers (demo values until GIA's)
    agents.py   the AGENT steps
    service.py  opening, invitation, the decision, the ERPNext customer, rules, daily review
    portal.py   the client's public application page (/api/v1/client-portal/...)
"""

from src.app.finance_pod.flows.ar_client_account import service
from src.app.finance_pod.flows.ar_client_account.spec import SPEC
from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register

register(
    SPEC,
    WorkflowHooks(
        actions=service.actions(),
        on_create=service.on_create,
        purposes={
            "client_invite": "Client portal invitation",
            "client_gaps": "What's missing from the application",
        },
    ),
)
