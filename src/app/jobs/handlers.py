"""Import every module that registers job handlers (the worker loads this)."""

import src.app.agent_catalog.runs.jobs  # noqa: F401 - run.narrative, quickbooks.writeback
