#!/usr/bin/env bash
# Move the server from docker-compose.yml (development stack) to docker-compose.prod.yml
# (production stack), copying the database. About 10 minutes of downtime, from "Stopping the
# old app" to the end. Stops at the first problem; nothing here deletes the old database, so
# deploy/rollback-to-dev.sh can always go back.
#
#   bash deploy/migrate-to-prod.sh
#
# Afterwards: point Caddy at 127.0.0.1:8081 (see the end of the output) and verify.
set -euo pipefail
cd "$(dirname "$0")/.."

PROD=(docker compose -f docker-compose.prod.yml --env-file .env.prod.generated-env)
STAMP=$(date +%Y%m%d-%H%M)
BACKUPS="${BACKUPS:-$HOME/finance-acc-backups}"
mkdir -p "$BACKUPS"
step() { printf '\n== %s ==\n' "$1"; }
if [[ -f .migrated-to-prod ]]; then
  echo "Already moved to docker-compose.prod.yml ($(cat .migrated-to-prod)): running this again would" >&2
  echo "replace the live database with the old one. To deploy new code instead:" >&2
  echo "  docker compose -f docker-compose.prod.yml up -d --build" >&2
  exit 1
fi
COUNTS="select (select count(*) from users) as users, (select count(*) from fpod_vendors) as vendors, (select count(*) from audit_events) as audit_events;"

step "1. Safety backup (site still up)"
[[ -n "$(docker compose ps -q --status running db)" ]] || { echo "The old database isn't running: start it with 'docker compose up -d db'." >&2; exit 1; }
docker compose exec -T db pg_dump -U finance -d finance_acc -Fc > "$BACKUPS/before-migration-$STAMP.dump"
[[ -s "$BACKUPS/before-migration-$STAMP.dump" ]] || { echo "The backup is empty: stopping." >&2; exit 1; }
ls -lh "$BACKUPS/before-migration-$STAMP.dump"
[[ -f /etc/caddy/Caddyfile ]] && sudo cp /etc/caddy/Caddyfile "$BACKUPS/Caddyfile-$STAMP" || true

step "2. Production settings (from .env.prod and the current secrets)"
# Build the production .env into a side file first; .env is switched in step 6
cp .env .env.before-prod-$STAMP
bash deploy/make-env.sh prod
mv .env .env.prod.generated-env
cp .env.before-prod-$STAMP .env      # the old stack keeps its settings until the switch
chmod 600 .env.prod.generated-env

step "3. Build the production images, start the new (empty) database (site still up)"
"${PROD[@]}" build
"${PROD[@]}" up -d db
for _ in $(seq 1 30); do
  "${PROD[@]}" ps db | grep -q "(healthy)" && break
  sleep 3
done
"${PROD[@]}" ps db | grep -q "(healthy)" || { echo "The new database didn't become healthy." >&2; exit 1; }

step "4. Stopping the old app (downtime starts)"
docker compose stop frontend backend worker

step "5. Final copy of the database into the new one"
docker compose exec -T db pg_dump -U finance -d finance_acc -Fc > "$BACKUPS/final-$STAMP.dump"
[[ -s "$BACKUPS/final-$STAMP.dump" ]] || { echo "The final dump is empty: run deploy/rollback-to-dev.sh" >&2; exit 1; }
# An empty database to restore into (a run after a rollback finds the earlier copy, now stale)
"${PROD[@]}" exec -T db psql -U finance -d postgres -q -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS finance_acc WITH (FORCE);" -c "CREATE DATABASE finance_acc;"
if ! "${PROD[@]}" exec -T db pg_restore -U finance -d finance_acc --no-owner --exit-on-error < "$BACKUPS/final-$STAMP.dump"; then
  echo "The restore failed: run deploy/rollback-to-dev.sh and send this output to the Finance AI team." >&2
  exit 1
fi
old=$(docker compose exec -T db psql -U finance -d finance_acc -At -c "$COUNTS")
new=$("${PROD[@]}" exec -T db psql -U finance -d finance_acc -At -c "$COUNTS")
echo "old database: $old"
echo "new database: $new"
[[ "$old" == "$new" ]] || { echo "The counts differ: run deploy/rollback-to-dev.sh" >&2; exit 1; }
docker compose stop db   # kept (not removed) for rollback

step "6. Switch the settings and start the production stack"
cp .env.prod.generated-env .env
chmod 600 .env
# "up" waits for the migrations; it fails if they fail
if ! docker compose -f docker-compose.prod.yml up -d; then
  docker compose -f docker-compose.prod.yml logs --tail 30 migrate
  echo "The migrations failed: run deploy/rollback-to-dev.sh and send this output to the Finance AI team." >&2
  exit 1
fi
for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/healthz || true)
  [[ "$code" == "200" ]] && break
  sleep 3
done
docker compose -f docker-compose.prod.yml ps
[[ "${code:-}" == "200" ]] || { echo "The new stack doesn't answer on 8081: see 'docker compose -f docker-compose.prod.yml logs backend'." >&2; exit 1; }
date '+%Y-%m-%d %H:%M' > .migrated-to-prod

cat <<MSG

== Done: the production stack answers on 127.0.0.1:8081 ==
Backups: $BACKUPS

Next:
 1. Caddy must send ALL traffic for finance.e-solutionsinc.com to 127.0.0.1:8081 (nginx passes
    /api to the backend itself). If the Caddyfile sends /api to 8088, change the site block to:
        finance.e-solutionsinc.com {
            encode gzip
            reverse_proxy 127.0.0.1:8081
        }
    then: sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
 2. Check: sign in; Data Sources > QuickBooks "Sync now" works; Finance POD > Vendors shows
    masked bank numbers. Then run: bash deploy/check.sh
 3. Azure network security group: inbound only 443 and 80 (and 22 from your IPs).
MSG
