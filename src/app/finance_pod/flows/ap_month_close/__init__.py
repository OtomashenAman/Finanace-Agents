"""AP-6 Month-End Close (Finance POD).

The close agent lists receipts not invoiced and proposes the accrual journal, reconciles the
payables subledger to the ledger (again daily) and reads the vendor statements uploaded to
the case; the controller reviews and signs off; the evidence pack is filed and the controller
posts the proposed journals, verified by a fresh snapshot.

    spec.py     the steps, rules, measures
    results.py  what each L5 step records
    policy.py   close day, key-vendor balance, tolerance (demo values until GIA's)
    agents.py   the AGENT steps (pure code on the snapshot)
    service.py  opening, sign-off (evidence, journals), rules, measures, the daily check
"""

from src.app.finance_pod.flows.ap_month_close import service
from src.app.finance_pod.flows.ap_month_close.spec import SPEC
from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register

register(SPEC, WorkflowHooks(on_create=service.on_create))
