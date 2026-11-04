"""One package per workflow. Importing this registers them all (specs, rules, endpoints);
screens list them in WorkflowKey order.

Adding a workflow: create flows/<key>/ with spec.py and an __init__.py that calls
core.registry.register(SPEC, WorkflowHooks(...), router), then import it here.
"""

from src.app.service_pod.flows import (  # noqa: F401
    ar_collections,
    bank_recon,
    fpa_trend,
    reporting,
    treasury,
)
