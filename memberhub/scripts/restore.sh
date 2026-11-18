#!/usr/bin/env bash
# Restore a Member Hub PostgreSQL backup. WARNING: replaces current data.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

: "${DATABASE_URL:?DATABASE_URL must be set in .env or the environment}"
FILE="${1:-}"
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "Usage: $0 backups/memberhub-YYYYMMDD-HHMMSS.dump" >&2
  exit 1
fi

echo "This will REPLACE all data in the database pointed to by DATABASE_URL."
read -r -p "Type RESTORE to continue: " CONFIRM
[ "$CONFIRM" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

pg_restore --clean --if-exists --no-owner --no-acl -d "$DATABASE_URL" "$FILE"
echo "Restore complete from $FILE"
