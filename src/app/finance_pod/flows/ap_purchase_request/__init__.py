"""AP-1 Purchase Request & Purchase Order (Finance POD).

A requester describes the need (form or chat, a quote if there is one); the request agent
codes and prices it and flags what's missing; the budget agent checks budget, grant rules
and the authority matrix; the budget owner approves, rejects or queries; the sourcing agent
finds vendors, asks for quotes above the threshold and compares them; the buyer chooses (a new
vendor opens an onboarding case); the PO agent drafts the PO, the buyer approves it above the
limit, and after the release the PO goes to ERPNext and to the vendor.

    spec.py     the steps (requirement codes and words), rules, measures
    results.py  what each L5 step records
    policy.py   thresholds (demo values until GIA's)
    agents.py   the AGENT steps
    service.py  opening, decisions' effects, rules, measures, the buyer's actions
"""

from src.app.finance_pod.flows.ap_purchase_request import service
from src.app.finance_pod.flows.ap_purchase_request.spec import SPEC
from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register

register(
    SPEC,
    WorkflowHooks(
        actions=service.actions(),
        on_create=service.on_create,
        purposes={"rfq": "Request for quotation", "purchase_order": "Purchase order"},
    ),
)
