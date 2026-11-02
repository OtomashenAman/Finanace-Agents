"""AP-1 L3 1.5 Vendor Onboarding (Finance POD).

The onboarding agent sends the vendor a signed portal link, reads the tax form and bank
letter they upload there, checks the tax ID and screens the OFAC SDN list; an AP analyst
confirms the bank by phone from an independent number; a second person activates the vendor;
the supplier is created in ERPNext and verified by a fresh snapshot.

    spec.py     the steps, rules, measure
    results.py  what each L5 step records (numbers masked; full ones encrypted)
    reading.py  reading the documents, checking a tax ID
    agents.py   the AGENT steps
    service.py  opening, call-back check, guardrails, the ERPNext supplier
    portal.py   the vendor's public upload page (/api/v1/vendor-portal/...)
"""

from src.app.finance_pod.flows.ap_vendor_onboarding import service
from src.app.finance_pod.flows.ap_vendor_onboarding.spec import SPEC
from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register

register(
    SPEC,
    WorkflowHooks(
        actions=service.actions(),
        on_create=service.on_create,
        extract_reply=service.read_reply,
        purposes={"vendor_invite": "Supplier portal invitation"},
    ),
)
