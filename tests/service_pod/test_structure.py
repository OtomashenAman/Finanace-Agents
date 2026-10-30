"""The module layout's own guarantees: every workflow registered, in a stable order, and
every background job known to the standalone worker (which loads only jobs.handlers)."""

import subprocess
import sys

from src.app.service_pod.core.hooks import HOOKS
from src.app.service_pod.core.workflows import WORKFLOWS, WorkflowKey


def test_every_workflow_is_registered_in_key_order() -> None:
    assert list(WORKFLOWS) == list(WorkflowKey)
    assert set(HOOKS) == {WorkflowKey.AR_COLLECTIONS, WorkflowKey.BANK_RECON}


def test_the_worker_knows_every_job() -> None:
    code = (
        "import src.app.jobs.handlers\n"
        "from src.app.jobs.queue import _HANDLERS\n"
        "print(' '.join(sorted(_HANDLERS)))"
    )
    out = subprocess.run(  # noqa: S603 - fixed arguments
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    for kind in ("pod.send_message", "pod.extract_reply", "audit.purge"):
        assert kind in out
