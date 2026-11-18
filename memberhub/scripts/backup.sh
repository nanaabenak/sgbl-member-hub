#!/usr/bin/env bash
# PostgreSQL backup for the Member Hub. Run from cron on the EC2 instance.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${DATABASE_URL:?DATABASE_URL must be set in .env or the environment}"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="$BACKUP_DIR/memberhub-$STAMP.dump"

pg_dump -Fc --no-owner --no-acl "$DATABASE_URL" -f "$FILE"
echo "Backup written to $FILE"

# Keep 30 days of local backups (adjust RETENTION_DAYS if needed).
find "$BACKUP_DIR" -name 'memberhub-*.dump' -type f -mtime "+${RETENTION_DAYS:-30}" -delete
