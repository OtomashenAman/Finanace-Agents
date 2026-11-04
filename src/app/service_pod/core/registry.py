"""How a workflow plugs into the Service POD: its spec, its rules (hooks) and its own
endpoints. Each package under flows/ calls register() once, when flows is imported."""

from fastapi import APIRouter

from src.app.service_pod.core.hooks import HOOKS, WorkflowHooks
from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey, WorkflowSpec

ROUTERS: list[APIRouter] = []


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
        ROUTERS.append(router)
