#!/bin/sh
# samvaad pgbackup loop: nightly pg_dump (custom format, incl. PGVector data)
# to /backups, keeping the 7 newest. Copy off-VM (see infra/DEPLOY.md).
set -eu

USER="${POSTGRES_USER:-rag_user}"
DB="${POSTGRES_DB:-rag_financial}"
INTERVAL="${BACKUP_INTERVAL_SECS:-86400}"

while true; do
  TS=$(date -u +%F_%H%M)
  FILE="/backups/rag_financial_${TS}.dump"
  if pg_dump -h postgres -U "$USER" -d "$DB" -Fc -f "$FILE"; then
    echo "[pgbackup] wrote $FILE"
  else
    echo "[pgbackup] pg_dump FAILED for $FILE" >&2
    rm -f "$FILE"
  fi
  ls -t /backups/rag_financial_*.dump 2>/dev/null | tail -n +8 | xargs -r rm -f
  sleep "$INTERVAL"
done
