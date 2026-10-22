"""Import every module that registers job handlers (the worker loads this)."""

import src.app.agent_catalog.runs.jobs
import src.app.audit.jobs  # audit.purge (daily)
import src.app.data_sources.service  # noqa: F401 - data_source.history
