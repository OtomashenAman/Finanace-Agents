"""Import every module that registers job handlers (the worker loads this)."""

import src.app.agent_catalog.runs.jobs
import src.app.audit.jobs  # audit.purge (daily)
import src.app.data_sources.service  # data_source.history
import src.app.service_pod.messaging.jobs  # noqa: F401 - pod.send_message
