# Optional shortcut for Linux/macOS: every target forwards to `uv run poe <target>`.
# Tasks are defined once in pyproject.toml ([tool.poe.tasks]) and work on Windows too:
#   uv run poe            # list tasks
#   uv run poe db-up
.DEFAULT_GOAL := help
.PHONY: help migration

help:
	@uv run poe

migration: ## make migration m="add runs table"
	@uv run poe migration "$(m)"

%:
	@uv run poe $@
