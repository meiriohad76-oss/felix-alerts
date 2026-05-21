#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/sentinel/sentinel.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

DB_PATH="${SENTINEL_DB_PATH:-/var/lib/sentinel/sentinel.sqlite3}"
BACKUP_DIR="${SENTINEL_BACKUP_DIR:-/var/backups/sentinel}"
RETENTION_DAYS="${SENTINEL_BACKUP_RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_PATH="$BACKUP_DIR/sentinel-$STAMP.sqlite3"

if [[ ! -f "$DB_PATH" ]]; then
  echo "Sentinel database not found: $DB_PATH" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required. Install with: sudo apt-get install -y sqlite3" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
sqlite3 "$DB_PATH" ".backup '$BACKUP_PATH'"
chmod 0640 "$BACKUP_PATH"
find "$BACKUP_DIR" -name 'sentinel-*.sqlite3' -type f -mtime +"$RETENTION_DAYS" -delete

echo "$BACKUP_PATH"
