#!/bin/sh
# Render start: migrate, sync the agent catalog, then serve (free plan has no pre-deploy step)
set -e
alembic upgrade head
python -m src.app.cli.sync_agents
exec uvicorn src.app.main:app --host 0.0.0.0 --port "${PORT:-8088}" \
  --proxy-headers --forwarded-allow-ips '*' --no-server-header
