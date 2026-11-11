# Shared by the deploy/ scripts (sourced, not run): which stack the server runs, and helpers.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ -f .migrated-to-prod ]]; then
  STACK="production (docker-compose.prod.yml)"
  COMPOSE=(docker compose -f docker-compose.prod.yml)
  HEALTH_URL=http://127.0.0.1:8081/healthz
else
  STACK="development (docker-compose.yml)"
  COMPOSE=(docker compose)
  HEALTH_URL=http://127.0.0.1:8088/health
fi
BACKUPS="${BACKUPS:-$HOME/finance-acc-backups}"

step() { printf '\n== %s ==\n' "$1"; }

# Wait up to ~2 minutes for the app to answer; returns 1 if it doesn't
wait_healthy() {
  local code=""
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)
    [[ "$code" == "200" ]] && { echo "app health: 200"; return 0; }
    sleep 3
  done
  echo "app health: ${code:-no answer} ($HEALTH_URL)" >&2
  return 1
}

# A compressed dump of the database into $BACKUPS; prints the file's path
dump_db() {
  local file
  mkdir -p "$BACKUPS"
  file="$BACKUPS/finance-acc-$1-$(date +%Y%m%d-%H%M%S).dump"
  "${COMPOSE[@]}" exec -T db pg_dump -U finance -d finance_acc -Fc > "$file"
  # A dump pg_restore can't list is broken: don't keep it
  if [[ ! -s "$file" ]] || ! "${COMPOSE[@]}" exec -T db pg_restore --list < "$file" > /dev/null; then
    rm -f "$file"
    echo "The database backup failed." >&2
    return 1
  fi
  chmod 600 "$file"
  echo "$file"
}
