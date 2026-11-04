"""Treasury Forecast (deck Treasury slides, TDD section 9).

A case is a rolling 13-week (91-day) cash forecast for one entity from a snapshot: cleared,
reconciled opening cash, the AR promises customers made (approved in AR Collections and
reviewed again here, tranche by tranche, with a probability) and the approved outflows. The
engine computes the daily cash, weekly summaries, buffer breaches and the Optimistic / Stress
scenarios (parts of events moved to explicit dates). No AI, no accounting, no payments: the
Finance Admin signs off as the Treasury Head, then as the CFO, once any breach has an owned
mitigation. Customer confirmations are AR Collections cases; actual cash is Bank-to-Invoice.

    spec.py      key, source data needed, the two sign-offs
    schemas.py   selection, payloads, the sources screen
    engine.py    opening cash checks and the forecast (no AI)
    service.py   opening a case, blockers, stage / phase
    actions.py   tranche review, scenario shifts
    views.py     sources, CSV export
    router.py    /pod/treasury/...
"""

from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register
from src.app.service_pod.flows.treasury.actions import ACTIONS
from src.app.service_pod.flows.treasury.router import router
from src.app.service_pod.flows.treasury.service import blockers, on_create, phase, stage, summary
from src.app.service_pod.flows.treasury.spec import SPEC

register(
    SPEC,
    WorkflowHooks(
        actions=ACTIONS,
        on_create=on_create,
        blockers=blockers,
        stage=stage,
        phase=phase,
        summary=summary,
    ),
    router,
)
