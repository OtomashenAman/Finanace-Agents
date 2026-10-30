"""Import every module that registers job handlers (the worker loads this).

These imports are only for their side effect, so a linter must never remove them
(tests/service_pod/test_structure.py checks the worker sees every job)."""

# ruff: noqa: F401
import src.app.agent_catalog.runs.jobs  # run narratives, write-back
import src.app.audit.jobs  # audit.purge (daily)
import src.app.data_sources.service  # data_source.history
import src.app.service_pod.core.messaging.extraction_job  # pod.extract_reply
import src.app.service_pod.core.messaging.jobs  # pod.send_message
import src.app.service_pod.core.messaging.mailbox_job  # pod.read_mailbox (periodic)
import src.app.service_pod.flows  # the workflows' hooks the jobs call
