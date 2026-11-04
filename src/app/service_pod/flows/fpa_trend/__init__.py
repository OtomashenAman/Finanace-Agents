"""FP&A Trend Intelligence (deck FP&A slides, TDD section 8).

A case is one period (consecutive months) of one source. The engine computes the trend pack
from the source alone; drivers come from Posted transactions reconciled to the GL. AI only
writes commentary citing the engine's facts. The Finance Admin signs off as the Finance Head.
There is no customer email. A correction is a manual journal the Finance Admin posts in
QuickBooks; a fresh source must prove it before the figures are recalculated.

    spec.py       key, source data needed, sign-off capacity
    schemas.py    selection, payloads, the AI's output, the periods screen
    engine.py     the trend pack (no AI)
    service.py    opening a case, blockers, stage / phase, facts, correction verification
    actions.py    commentary by hand, mapping review, corrections
    narrative.py  AI commentary
    views.py      periods, drill, evidence CSV, approved pack
    router.py     /pod/fpa/...
"""

from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register
from src.app.service_pod.flows.fpa_trend.actions import ACTIONS
from src.app.service_pod.flows.fpa_trend.router import router
from src.app.service_pod.flows.fpa_trend.service import (
    blockers,
    completion_blockers,
    on_create,
    phase,
    stage,
    summary,
    verify_posting,
)
from src.app.service_pod.flows.fpa_trend.spec import SPEC

register(
    SPEC,
    WorkflowHooks(
        actions=ACTIONS,
        on_create=on_create,
        blockers=blockers,
        stage=stage,
        phase=phase,
        summary=summary,
        completion_blockers=completion_blockers,
        verify_posting=verify_posting,
    ),
    router,
)
