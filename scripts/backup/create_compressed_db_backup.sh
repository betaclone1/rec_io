#!/usr/bin/env bash
# Create a compressed full PostgreSQL dump (same idea as System UI → Backup Database).
#
# Output: <repo>/backup/db_backups/rec_io_db_backup_YYYYMMDD_HHMMSS.sql.gz
# Uses DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD from env or project .env
# (falls back to POSTGRES_* then package_user_data defaults).
#
# Usage (from repo root):
#   ./scripts/backup/create_compressed_db_backup.sh
#   DB_BACKUP_OUT_DIR=/tmp/backups ./scripts/backup/create_compressed_db_backup.sh
#
# Prints the absolute path of the created .sql.gz on the last stdout line (for callers).

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

_env_get() {
  local key="$1"
  local val="${!key:-}"
  if [[ -n "${val}" ]]; then
    printf '%s' "$val"
    return 0
  fi
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
    if [[ -n "$line" ]]; then
      printf '%s' "${line#*=}" | tr -d '\r' | sed 's/^["'\'']//; s/["'\'']$//'
      return 0
    fi
  fi
  return 1
}

DB_HOST="$(_env_get DB_HOST || true)"
[[ -z "$DB_HOST" ]] && DB_HOST="$(_env_get POSTGRES_HOST || true)"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="$(_env_get DB_PORT || true)"
[[ -z "$DB_PORT" ]] && DB_PORT="$(_env_get POSTGRES_PORT || true)"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="$(_env_get DB_NAME || true)"
[[ -z "$DB_NAME" ]] && DB_NAME="$(_env_get POSTGRES_DB || true)"
DB_NAME="${DB_NAME:-rec_io_db}"
DB_USER="$(_env_get DB_USER || true)"
[[ -z "$DB_USER" ]] && DB_USER="$(_env_get POSTGRES_USER || true)"
DB_USER="${DB_USER:-rec_io_user}"
DB_PASSWORD="$(_env_get DB_PASSWORD || true)"
[[ -z "$DB_PASSWORD" ]] && DB_PASSWORD="$(_env_get POSTGRES_PASSWORD || true)"
DB_PASSWORD="${DB_PASSWORD:-rec_io_password}"
export PGPASSWORD="$DB_PASSWORD"

OUT_DIR="${DB_BACKUP_OUT_DIR:-$PROJECT_ROOT/backup/db_backups}"
mkdir -p "$OUT_DIR"

# Resolve pg_dump (same search order as package_user_data.sh)
PG_DUMP=""
if command -v pg_dump >/dev/null 2>&1; then
  PG_DUMP="pg_dump"
fi
if [[ -z "$PG_DUMP" && -d /opt/homebrew/opt ]]; then
  for f in /opt/homebrew/opt/postgresql@*/bin/pg_dump; do
    if [[ -x "$f" ]]; then PG_DUMP="$f"; break; fi
  done
fi
if [[ -z "$PG_DUMP" && -x /opt/homebrew/bin/pg_dump ]]; then
  PG_DUMP="/opt/homebrew/bin/pg_dump"
fi
if [[ -z "$PG_DUMP" && -x /usr/local/bin/pg_dump ]]; then
  PG_DUMP="/usr/local/bin/pg_dump"
fi
if [[ -z "$PG_DUMP" && -x /usr/bin/pg_dump ]]; then
  PG_DUMP="/usr/bin/pg_dump"
fi
if [[ -z "$PG_DUMP" ]]; then
  echo "create_compressed_db_backup: pg_dump not found" >&2
  exit 1
fi

TS="$(TZ="${TZ:-America/New_York}" date +%Y%m%d_%H%M%S)"
OUT_FILE="$OUT_DIR/rec_io_db_backup_${TS}.sql.gz"

echo "create_compressed_db_backup: dumping ${DB_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "create_compressed_db_backup: writing $OUT_FILE"

# Full DB dump (clean/create) compressed with gzip — portable restore via gunzip | psql
if ! "$PG_DUMP" \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --clean \
  --if-exists \
  --create \
  | gzip -c >"$OUT_FILE"; then
  rm -f "$OUT_FILE"
  echo "create_compressed_db_backup: pg_dump failed" >&2
  exit 1
fi

SIZE="$(du -h "$OUT_FILE" | awk '{print $1}')"
echo "create_compressed_db_backup: ok size=${SIZE}"
echo "$OUT_FILE"
