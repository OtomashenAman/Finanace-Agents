#!/usr/bin/env bash
# Build the server's .env from .env.prod (sent by the Finance AI team) and the server's
# current .env, keeping the secrets the running system depends on. Prints no secret.
#
#   bash deploy/make-env.sh dev    # for docker-compose.yml   (what the server runs today)
#   bash deploy/make-env.sh prod   # for docker-compose.prod.yml (after the migration)
#
# Kept from the current .env (backed up once to .env.dev-backup):
#   SECRET_KEY           the same value (a new one would sign everyone out)
#   DATA_ENCRYPTION_KEY  the same value; if there is none, the key the app has been deriving
#                        from SECRET_KEY, so saved QuickBooks connections and bank details
#                        stay readable
#   POSTGRES_PASSWORD    dev: the database's existing password ("finance" if never set)
#                        prod: a new random one for the new database (unless one is set)
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-}"
LOST="${2:-}"
if [[ "$MODE" != "dev" && "$MODE" != "prod" ]]; then
  echo "Usage: bash deploy/make-env.sh dev|prod [--original-lost]" >&2
  exit 2
fi
[[ -f .env.prod ]] || { echo "Missing .env.prod (from the Finance AI team) in $(pwd)" >&2; exit 1; }

# The original .env, saved once and never overwritten: every later run reads from it
if [[ ! -f .env.dev-backup ]]; then
  [[ -f .env ]] || { echo "Missing the server's current .env" >&2; exit 1; }
  if grep -q "KEEP_THE_EXISTING_VALUE" .env && [[ "$LOST" != "--original-lost" ]]; then
    cat >&2 <<'MSG'
The current .env is the earlier template (it contains KEEP_THE_EXISTING_VALUE), not the
server's original settings. Put the ORIGINAL .env (from before the update: a backup, an
earlier copy, the VM snapshot) at .env.dev-backup in this directory, and run this again.

Only if the original is really gone, run:  bash deploy/make-env.sh dev --original-lost
That makes a new SECRET_KEY: everyone signs in again, saved QuickBooks connections must be
connected again (Data Sources), and vendor bank details saved before must be entered again.
MSG
    exit 1
  fi
  cp .env .env.dev-backup
  chmod 600 .env.dev-backup
  echo "Saved the current .env as .env.dev-backup"
fi
OLD=.env.dev-backup
if grep -q "KEEP_THE_EXISTING_VALUE" "$OLD"; then
  if [[ "$LOST" != "--original-lost" ]]; then
    echo ".env.dev-backup holds the template, not the original settings: see the message above" >&2
    echo "(replace .env.dev-backup with the original .env, or run with --original-lost)." >&2
    exit 1
  fi
  # Original secrets gone: start from new ones (the database password stays the default)
  sed -i -e 's/^SECRET_KEY=.*/SECRET_KEY=/' -e 's/^DATA_ENCRYPTION_KEY=.*/DATA_ENCRYPTION_KEY=/' \
    -e 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=/' "$OLD"
  echo "SECRET_KEY=$(openssl rand -hex 32)" >> "$OLD"
  echo "Original secrets lost: new SECRET_KEY written to .env.dev-backup (QuickBooks must be"
  echo "connected again, and saved vendor bank details entered again)."
fi

# The value of KEY in FILE (last one wins), without surrounding quotes; empty if absent
value() {
  local line
  line=$(grep -E "^[[:space:]]*$1=" "$2" | tail -n 1 || true)
  line="${line#*=}"
  line="${line%$'\r'}"
  if [[ "$line" =~ ^\"(.*)\"$ || "$line" =~ ^\'(.*)\'$ ]]; then line="${BASH_REMATCH[1]}"; fi
  printf '%s' "$line"
}

# The key the app derives from SECRET_KEY when DATA_ENCRYPTION_KEY is empty (data_sources/crypto.py)
derive_key() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import base64,hashlib,sys; print(base64.urlsafe_b64encode(hashlib.sha256(b"finance-acc/data-sources:"+sys.argv[1].encode()).digest()).decode())' "$1"
  else
    printf 'finance-acc/data-sources:%s' "$1" | openssl dgst -sha256 -binary | base64 | tr '+/' '-_'
  fi
}

SECRET=$(value SECRET_KEY "$OLD")
KEY=$(value DATA_ENCRYPTION_KEY "$OLD")
PASS=$(value POSTGRES_PASSWORD "$OLD")

if [[ -z "$SECRET" ]]; then
  echo "The current .env has no SECRET_KEY: ask the Finance AI team before continuing." >&2
  exit 1
fi
if [[ -z "$KEY" ]]; then
  KEY=$(derive_key "$SECRET")
  key_note="derived from the current SECRET_KEY (the key the app was already using)"
else
  key_note="kept from the current .env"
fi
# Values generated for production are saved once (.env.generated) and reused on every later
# run: a second, different password would no longer match the database created with the first
GEN=.env.generated
secret_note="kept from the current .env"
if [[ "$MODE" == "prod" && ( ${#SECRET} -lt 32 || "$SECRET" == "change-me" ) ]]; then
  # Production refuses a short SECRET_KEY. The encryption key above is already fixed, so
  # changing SECRET_KEY now only signs users out once.
  if [[ -f "$GEN" && -n "$(value SECRET_KEY "$GEN")" ]]; then
    SECRET=$(value SECRET_KEY "$GEN")
  else
    SECRET=$(openssl rand -hex 32)
    echo "SECRET_KEY=$SECRET" >> "$GEN"
  fi
  secret_note="NEW (the old one was too short for production: users sign in again once)"
fi
if [[ "$MODE" == "dev" ]]; then
  PASS="${PASS:-finance}"
  pass_note="the database's existing password"
elif [[ -z "$PASS" || "$PASS" == "finance" ]]; then
  if [[ -f "$GEN" && -n "$(value POSTGRES_PASSWORD "$GEN")" ]]; then
    PASS=$(value POSTGRES_PASSWORD "$GEN")
  else
    PASS=$(openssl rand -hex 24)
    echo "POSTGRES_PASSWORD=$PASS" >> "$GEN"
  fi
  pass_note="NEW random password for the new production database (saved in $GEN)"
else
  pass_note="kept from the current .env"
fi
[[ -f "$GEN" ]] && chmod 600 "$GEN"

# .env.prod with the three values filled in
tmp=$(mktemp)
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    SECRET_KEY=*) printf 'SECRET_KEY="%s"\n' "$SECRET" ;;
    DATA_ENCRYPTION_KEY=*) printf 'DATA_ENCRYPTION_KEY="%s"\n' "$KEY" ;;
    POSTGRES_PASSWORD=*) printf 'POSTGRES_PASSWORD=%s\n' "$PASS" ;;
    *) printf '%s\n' "$line" ;;
  esac
done < .env.prod > "$tmp"
mv "$tmp" .env
chmod 600 .env

echo "Wrote .env for docker-compose$([[ "$MODE" == "prod" ]] && echo ".prod").yml:"
echo "  SECRET_KEY           $secret_note"
echo "  DATA_ENCRYPTION_KEY  $key_note"
echo "  POSTGRES_PASSWORD    $pass_note"
