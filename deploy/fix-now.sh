#!/usr/bin/env bash
# Fix "password authentication failed for user finance" on the current setup
# (docker-compose.yml): rebuild .env from .env.prod with the server's existing secrets,
# restart, and check. Safe to run again. Never deletes data.
#
#   bash deploy/fix-now.sh
set -euo pipefail
cd "$(dirname "$0")/.."

bash deploy/make-env.sh dev

echo
echo "== Starting (migrations run first) =="
docker compose up -d --build

echo
echo "== Migrations =="
if docker compose logs migrate 2>&1 | grep -q "password authentication failed"; then
  echo "Still a password error: the database was created with another password." >&2
  echo "Put that password in .env.dev-backup as POSTGRES_PASSWORD=... and run this again," >&2
  echo "or ask the Finance AI team." >&2
  exit 1
fi
docker compose logs --tail 15 migrate

echo
echo "== Health =="
for _ in $(seq 1 24); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/health || true)
  [[ "$code" == "200" ]] && break
  sleep 5
done
echo "backend /health: ${code:-no answer}"
docker compose ps
[[ "${code:-}" == "200" ]] && echo "OK: open https://finance.e-solutionsinc.com and sign in."
