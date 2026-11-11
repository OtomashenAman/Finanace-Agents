#!/usr/bin/env bash
# Deploy the latest main: back up the database, pull, rebuild, restart (migrations run first),
# check. Use this for every release.
#
#   bash deploy/update.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"

before=$(git rev-parse --short HEAD)
echo "Stack: $STACK, now at $before"

step "1. Database backup"
dump_db before-update

step "2. Latest code"
git pull --ff-only
after=$(git rev-parse --short HEAD)
if [[ "$after" == "$before" ]]; then
  echo "Already up to date; rebuilding anyway."
else
  git log --oneline "$before..$after" | head -20
fi

step "3. Build and restart"
if ! "${COMPOSE[@]}" up -d --build; then
  "${COMPOSE[@]}" logs --tail 30 migrate
  echo "Start failed. Back to the previous version: git checkout $before && bash deploy/update.sh" >&2
  echo "(a failed migration changes nothing; if one ran, also restore the backup above)" >&2
  exit 1
fi
wait_healthy || {
  echo "See: ${COMPOSE[*]} logs --tail 50 backend" >&2
  exit 1
}
echo "Deployed $after."
