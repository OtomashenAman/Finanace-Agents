"""FP&A Trend Intelligence (deck slides 13-20). Phase 3.

Only the spec so far: roles can be assigned and cases opened on a snapshot that has the
data it needs. The workflow's own rules (service.py, reading.py, views.py, router.py) plug
in through WorkflowHooks the same way as ar_collections and bank_recon."""

from src.app.service_pod.core.registry import register
from src.app.service_pod.flows.fpa_trend.spec import SPEC

register(SPEC)
