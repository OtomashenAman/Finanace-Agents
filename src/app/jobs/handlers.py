"""Import every module that registers job handlers (the worker loads this)."""

import src.app.agent_catalog.runs.jobs
import src.app.audit.jobs  # noqa: F401 - audit.purge (daily)
