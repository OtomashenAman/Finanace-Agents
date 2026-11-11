#!/usr/bin/env bash
# Back up the database to ~/finance-acc-backups (BACKUPS=... to change), keeping 14 days
# (KEEP_DAYS=... to change). The site stays up.
#
#   bash deploy/backup-db.sh                 # one backup now
#   bash deploy/backup-db.sh --install-cron  # every night at 02:30, logged to backup.log
#
# Also copy the backups off the server (Azure Blob, another VM): a backup on the same disk
# doesn't survive losing the VM.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

if [[ "${1:-}" == "--install-cron" ]]; then
  mkdir -p "$BACKUPS"
  line="30 2 * * * cd $(pwd) && bash deploy/backup-db.sh >> $BACKUPS/backup.log 2>&1"
  if crontab -l 2>/dev/null | grep -qF "deploy/backup-db.sh"; then
    echo "Already scheduled:"; crontab -l | grep -F "deploy/backup-db.sh"
  else
    (crontab -l 2>/dev/null || true; echo "$line") | crontab -
    echo "Scheduled: $line"
  fi
  exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') backup of the $STACK database"
file=$(dump_db daily)
ls -lh "$file"
find "$BACKUPS" -name 'finance-acc-*.dump' -mtime +"${KEEP_DAYS:-14}" -print -delete | sed 's/^/removed old: /'
