#!/usr/bin/env bash
# Is the server healthy? Containers, health, migrations, settings in use, latest backup, ports.
#
#   bash deploy/check.sh
set -uo pipefail
source "$(dirname "$0")/lib.sh"

echo "Stack: $STACK, code $(git rev-parse --short HEAD) ($(git log -1 --format=%cd --date=short))"
step "Containers"
"${COMPOSE[@]}" ps
step "Health"
echo "app:                       $(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL")"
echo "public /healthz via Caddy: $(curl -s -o /dev/null -w '%{http_code}' https://finance.e-solutionsinc.com/healthz)"
step "Migrations (last lines)"
"${COMPOSE[@]}" logs --tail 5 migrate
step "Settings the backend runs with (no secrets)"
"${COMPOSE[@]}" exec -T backend sh -c 'echo "ENVIRONMENT=$ENVIRONMENT"; echo "EMAIL_PROVIDER=$EMAIL_PROVIDER MS_MAILBOX=$MS_MAILBOX"; echo "EMAIL_TEST_RECIPIENT=${EMAIL_TEST_RECIPIENT:-(empty: live)}"; echo "PUBLIC_BASE_URL=$PUBLIC_BASE_URL"'
step "Finance Admins"
"${COMPOSE[@]}" exec -T backend python -m src.app.cli.admin list | grep '^finance_admin' || true
step "Latest database backup"
ls -1t "$BACKUPS"/finance-acc-*.dump 2>/dev/null | head -1 || true
crontab -l 2>/dev/null | grep -qF deploy/backup-db.sh && echo "nightly backup: scheduled" \
  || echo "nightly backup: NOT scheduled (bash deploy/backup-db.sh --install-cron)"
step "Ports open on all interfaces (only 22, 80, 443 should be reachable from the internet)"
ss -ltn 2>/dev/null | awk 'NR==1 || $4 ~ /^(0\.0\.0\.0|\*|\[::\]):/'
