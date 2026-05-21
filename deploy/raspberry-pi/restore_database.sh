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
RESTORE_PATH="${1:-}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
PRE_RESTORE_BACKUP="$BACKUP_DIR/sentinel-prerestore-$STAMP.sqlite3"

if [[ -z "$RESTORE_PATH" ]]; then
  echo "Usage: sudo /opt/sentinel/deploy/raspberry-pi/restore_database.sh /path/to/sentinel-backup.sqlite3" >&2
  exit 2
fi

if [[ ! -f "$RESTORE_PATH" ]]; then
  echo "Backup file not found: $RESTORE_PATH" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required. Install with: sudo apt-get install -y sqlite3" >&2
  exit 1
fi

INTEGRITY_RESULT="$(sqlite3 "$RESTORE_PATH" "PRAGMA integrity_check;")"
if [[ "$INTEGRITY_RESULT" != "ok" ]]; then
  echo "Restore file failed SQLite integrity check: $INTEGRITY_RESULT" >&2
  exit 1
fi

SERVICE_WAS_ACTIVE=0
if systemctl is-active --quiet sentinel; then
  SERVICE_WAS_ACTIVE=1
fi

restart_original_service_on_error() {
  if [[ "$SERVICE_WAS_ACTIVE" -eq 1 ]]; then
    systemctl start sentinel || true
  fi
}

trap restart_original_service_on_error ERR

systemctl stop sentinel
mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$DB_PATH")"
if [[ -f "$DB_PATH" ]]; then
  sqlite3 "$DB_PATH" ".backup '$PRE_RESTORE_BACKUP'"
  chmod 0640 "$PRE_RESTORE_BACKUP"
  echo "Created pre-restore backup: $PRE_RESTORE_BACKUP"
fi
cp "$RESTORE_PATH" "$DB_PATH"
chmod 0640 "$DB_PATH"
if id sentinel >/dev/null 2>&1; then
  chown sentinel:sentinel "$DB_PATH"
fi
systemctl start sentinel
trap - ERR

echo "Restored Sentinel database from $RESTORE_PATH to $DB_PATH"
