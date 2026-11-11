#!/usr/bin/env bash
# Go back to docker-compose.yml (the setup before deploy/migrate-to-prod.sh), with the old
# database as it was when the migration stopped the old app. Changes made on the production
# stack after the switch are NOT carried back. Keeps the production database (not deleted).
#
#   bash deploy/rollback-to-dev.sh
#
# Afterwards, if Caddy was changed: put back the Caddyfile saved in ~/finance-acc-backups.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Stopping the production stack (its database is kept) =="
docker compose -f docker-compose.prod.yml stop || true
rm -f .migrated-to-prod

echo "== Settings for docker-compose.yml =="
bash deploy/make-env.sh dev

echo "== Starting the old stack =="
docker compose up -d --build
for _ in $(seq 1 24); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/health || true)
  [[ "$code" == "200" ]] && break
  sleep 5
done
docker compose ps
echo "backend /health: ${code:-no answer}"
[[ "${code:-}" == "200" ]] || { echo "The old stack doesn't answer: see 'docker compose logs backend'." >&2; exit 1; }
echo "Rolled back. If Caddy was changed, restore the saved Caddyfile and run: sudo systemctl reload caddy"
