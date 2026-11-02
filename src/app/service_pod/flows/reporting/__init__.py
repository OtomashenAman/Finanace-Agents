"""Financial Reporting (deck Reporting slides, TDD section 10).

A case is one closed report month of one source, compared with the calendar month before. The
FP&A engine gives the P&L trend and drivers; this workflow adds the Balance Sheet checks,
the close status, AR aging (with its own as-of date) and the management pack. AI writes only
cited commentary. The Finance Admin signs off as the Controller, then as the CFO; only then is
the PDF pack exported (stored immutably, hash-checked) and sent to internal recipients.

    spec.py      key, source data needed, the two sign-offs
    schemas.py   selection and the screens' responses
    engine.py    statements and controls (no AI)
    service.py   opening a case, the aging scope task, blockers, stage / phase, facts, email
    models.py    stored packs
    pdf.py       the PDF writer
    packs.py     export, list and read packs
    views.py     report months
    router.py    /pod/reporting/...
"""

from src.app.service_pod.core.hooks import WorkflowHooks
from src.app.service_pod.core.registry import register
from src.app.service_pod.core.workflows import WorkflowKey
from src.app.service_pod.flows.fpa_trend import narrative
from src.app.service_pod.flows.fpa_trend.actions import ACTIONS as FPA_ACTIONS
from src.app.service_pod.flows.fpa_trend.service import verify_posting
from src.app.service_pod.flows.reporting.router import router
from src.app.service_pod.flows.reporting.service import (
    PURPOSES,
    after_create,
    blockers,
    completion_blockers,
    compose,
    draft_blocker,
    facts,
    on_create,
    phase,
    stage,
    summary,
)
from src.app.service_pod.flows.reporting.spec import SPEC

# The commentary, the mapping review and corrections work exactly as in FP&A
ACTIONS = {
    k: FPA_ACTIONS[k]
    for k in (
        "set_commentary",
        "confirm_mapping",
        "propose_correction",
        "withdraw_correction",
        "queue_correction",
    )
}
narrative.register(WorkflowKey.REPORTING, facts, "the Controller and the CFO")

register(
    SPEC,
    WorkflowHooks(
        actions=ACTIONS,
        on_create=on_create,
        after_create=after_create,
        blockers=blockers,
        purposes=PURPOSES,
        draft_blocker=draft_blocker,
        compose=compose,
        stage=stage,
        phase=phase,
        summary=summary,
        completion_blockers=completion_blockers,
        verify_posting=verify_posting,
    ),
    router,
)
