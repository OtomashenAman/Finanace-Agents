"""The Finance POD's registry and the requirement map name the same workflows."""

from src.app.finance_pod.requirements import PHASES
from src.app.service_pod.core.registry import ROUTERS
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey, workflows_in


def test_every_phase_names_registered_finance_workflows() -> None:
    named = {key for phase in PHASES for key in phase.workflows}
    for key in named:
        assert key in WORKFLOWS, f"{key} is named in the requirement but not registered"
        assert WORKFLOWS[key].pod == PodKey.FINANCE, key  # type: ignore[index]


def test_every_finance_workflow_implements_a_phase() -> None:
    named = {key for phase in PHASES for key in phase.workflows}
    for spec in workflows_in(PodKey.FINANCE):
        assert spec.key.value in named, f"{spec.key} implements no phase of the requirement"
        assert spec.plan.steps, f"{spec.key} declares no steps"


def test_service_pod_workflows_stay_admin_only_and_stepless() -> None:
    for spec in workflows_in(PodKey.SERVICE):
        assert not spec.plan.steps, spec.key
        assert not spec.signoff_sod, spec.key
    assert len(ROUTERS[PodKey.SERVICE]) == len(workflows_in(PodKey.SERVICE))
