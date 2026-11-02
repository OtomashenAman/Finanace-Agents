"""How a workflow plugs into its POD: its spec, its rules (hooks) and its own endpoints.
Each package under service_pod/flows/ and finance_pod/flows/ calls register() once, when
its flows package is imported. A workflow's router is mounted under its own POD only."""

from fastapi import APIRouter

from src.app.service_pod.core.hooks import HOOKS, WorkflowHooks
from src.app.service_pod.core.workflows import WORKFLOWS, PodKey, WorkflowKey, WorkflowSpec

ROUTERS: dict[PodKey, list[APIRouter]] = {pod: [] for pod in PodKey}


def register(
    spec: WorkflowSpec, hooks: WorkflowHooks | None = None, router: APIRouter | None = None
) -> None:
    if spec.key in WORKFLOWS:
        raise RuntimeError(f"Workflow {spec.key} is registered twice.")
    WORKFLOWS[spec.key] = spec
    # Screens list workflows in WorkflowKey order, whatever order the packages load in
    ordered = sorted(WORKFLOWS.items(), key=lambda item: list(WorkflowKey).index(item[0]))
    WORKFLOWS.clear()
    WORKFLOWS.update(ordered)
    if hooks is not None:
        HOOKS[spec.key] = hooks
    if router is not None:
        ROUTERS[spec.pod].append(router)
