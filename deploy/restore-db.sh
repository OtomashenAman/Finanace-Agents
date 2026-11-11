#!/usr/bin/env bash
# Replace the database with a backup (from deploy/backup-db.sh or any pg_dump -Fc file).
# Everything changed after that backup is lost, so the current database is backed up first.
# The site is down for a few minutes.
#
#   bash deploy/restore-db.sh ~/finance-acc-backups/finance-acc-daily-20261111-023000.dump
set -euo pipefail
source "$(dirname "$0")/lib.sh"

file="${1:-}"
[[ -s "$file" ]] || { echo "Usage: bash deploy/restore-db.sh <backup .dump file>" >&2; exit 2; }
"${COMPOSE[@]}" exec -T db pg_restore --list < "$file" > /dev/null \
  || { echo "$file isn't a readable database backup." >&2; exit 1; }

echo "This REPLACES the $STACK database with:"
ls -lh "$file"
if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "Type RESTORE to continue: " answer
  [[ "$answer" == "RESTORE" ]] || { echo "Nothing changed."; exit 1; }
fi

step "1. Backup of the current database"
dump_db before-restore

step "2. Stopping the app"
"${COMPOSE[@]}" stop frontend backend worker

step "3. Restoring"
"${COMPOSE[@]}" exec -T db psql -U finance -d postgres -q -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS finance_acc WITH (FORCE);" -c "CREATE DATABASE finance_acc;"
"${COMPOSE[@]}" exec -T db pg_restore -U finance -d finance_acc --no-owner --exit-on-error < "$file"
"${COMPOSE[@]}" exec -T db psql -U finance -d finance_acc -At \
  -c "select 'users: ' || count(*) from users;"

step "4. Starting the app (migrations bring an older backup up to date)"
"${COMPOSE[@]}" up -d
wait_healthy
