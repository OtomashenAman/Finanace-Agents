"""One package per Finance POD workflow. Importing this registers them all.

Adding a workflow: follow docs/plans/finance-pod-base-and-ap1.md, Part B. In short, create
flows/<key>/ with spec.py (WorkflowSpec with pod=FINANCE and its StepPlan: the
requirement's L4/L5 steps, rules and measures), agents.py (one handler per agent step) and
an __init__.py that calls core.registry.register(SPEC, WorkflowHooks(...), router); import
it here and name it in the phase's `workflows` in requirements/.
"""

from src.app.finance_pod.flows import (  # noqa: F401
    ap_invoice_match,
    ap_month_close,
    ap_purchase_request,
    ap_vendor_onboarding,
    ar_billing,
    ar_client_account,
)
