#!/usr/bin/env bash
# Quick check of the production stack: containers, health, migrations, exposed ports.
#
#   bash deploy/check.sh
set -uo pipefail
cd "$(dirname "$0")/.."
P=(docker compose -f docker-compose.prod.yml)

echo "== Containers =="
"${P[@]}" ps
echo
echo "== Health =="
echo "nginx  /healthz:            $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/healthz)"
echo "public /healthz (via Caddy):$(curl -s -o /dev/null -w '%{http_code}' https://finance.e-solutionsinc.com/healthz)"
echo
echo "== Migrations (last lines) =="
"${P[@]}" logs --tail 5 migrate
echo
echo "== Settings the backend runs with (no secrets) =="
"${P[@]}" exec -T backend sh -c 'echo "ENVIRONMENT=$ENVIRONMENT"; echo "EMAIL_PROVIDER=$EMAIL_PROVIDER MS_MAILBOX=$MS_MAILBOX"; echo "EMAIL_TEST_RECIPIENT=${EMAIL_TEST_RECIPIENT:-(empty: live)}"; echo "PUBLIC_BASE_URL=$PUBLIC_BASE_URL"'
echo
echo "== Ports listening on all interfaces (only 22, 80, 443 should be reachable from the internet) =="
ss -ltn 2>/dev/null | awk 'NR==1 || $4 ~ /^(0\.0\.0\.0|\*|\[::\]):/'
