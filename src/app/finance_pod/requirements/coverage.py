"""Hold workflows to the requirement: every To-Be L4/L5 step declared once, with the slide's
kind and words; every agent step with its agent, every person step with its capacity; every
checkpoint, rule, guardrail, pain point and measure implemented (and each rule tested), or
recorded as out of scope with a reason.
"""

import re

from src.app.finance_pod.requirements.model import Phase
from src.app.service_pod.core.steps.spec import StepKind, StepSpec
from src.app.service_pod.core.workflows import WorkflowSpec

PERSON_KINDS = (StepKind.PERSON, StepKind.MANUAL)


def claimed_ids(test_sources: str) -> set[str]:
    """The requirement ids that tests claim: @pytest.mark.requirement("AP1.R1", ...)."""
    found: set[str] = set()
    for args in re.findall(r"requirement\(([^)]*)\)", test_sources):
        found.update(re.findall(r"[\"']([A-Z]{2}\d+\.[A-Z]\d+)[\"']", args))
    return found


def problems(phase: Phase, specs: list[WorkflowSpec], test_sources: str) -> list[str]:
    out: list[str] = []
    declared: dict[str, list[tuple[WorkflowSpec, StepSpec, str]]] = {}
    for spec in specs:
        for step in spec.plan.steps:
            for l5 in step.l5:
                declared.setdefault(l5.code, []).append((spec, step, l5.text))

    for task in phase.tasks():
        for code, text in task.steps:
            where = declared.get(code, [])
            if not where:
                out.append(f"{phase.id} {code} ({text}) isn't a step of any workflow.")
                continue
            if len(where) > 1:
                names = ", ".join(spec.key for spec, _, _ in where)
                out.append(f"{phase.id} {code} is declared more than once ({names}).")
            spec, step, declared_text = where[0]
            if step.l4 != task.code:
                out.append(f"{code} belongs to L4 {task.code}, not {step.l4} ({spec.key}).")
            if step.kind != task.kind:
                out.append(
                    f"{code}: the requirement makes {task.code} a {task.kind.value} task, "
                    f"{spec.key} declares {step.kind.value}."
                )
            if declared_text != text:
                out.append(f"{code}: text {declared_text!r} differs from the requirement {text!r}.")

    for spec in specs:
        for step in spec.plan.steps:
            if step.kind == StepKind.AGENT and step.handler is None:
                out.append(f"{spec.key} {step.key} is an agent step without an agent.")
            if step.kind in PERSON_KINDS and not step.capacity:
                out.append(f"{spec.key} {step.key} is a person's step without a capacity.")
            for other in step.after:
                if spec.plan.step(other) is None:
                    out.append(f"{spec.key} {step.key} waits on unknown step {other}.")

    held = {s.capacity for spec in specs for s in spec.plan.steps if s.kind in PERSON_KINDS}
    held |= {cap for spec in specs for cap in spec.signoffs}
    for checkpoint in phase.checkpoints:
        if checkpoint.capacity not in held:
            out.append(
                f"{phase.id} checkpoint {checkpoint.text!r} has no step or sign-off "
                f"held by {checkpoint.capacity}."
            )

    rules = {rule.id: rule for spec in specs for rule in spec.plan.rules}
    tested = claimed_ids(test_sources)
    for item in phase.items:
        if item.out_of_scope:
            continue
        rule = rules.get(item.id)
        if rule is None:
            out.append(f"{item.id} ({item.kind.value}: {item.text}) isn't implemented.")
            continue
        if rule.check is None and not rule.enforced_by:
            out.append(f"{item.id} has neither a check nor an enforced_by note.")
        if item.id not in tested:
            out.append(f'{item.id} has no test marked @pytest.mark.requirement("{item.id}").')

    measures = {m.id for spec in specs for m in spec.plan.measures}
    out.extend(
        f"{phase.id} measure {m.id} ({m.text}) isn't computed."
        for m in phase.measures
        if m.id not in measures
    )
    return out
