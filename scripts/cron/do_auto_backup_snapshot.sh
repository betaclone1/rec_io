#!/usr/bin/env bash
# Nightly redundant backups:
#   1) DigitalOcean droplet auto_backup_* snapshot (rolling keep=5)
#   2) Compressed full Postgres dump → Google Drive DATA/DB_BACKUPS (rolling keep=14)
#
# Prereqs:
#   DIGITALOCEAN_API_TOKEN in .env (for step 1)
#   DB_* in .env + pg_dump on PATH (for step 2)
#   Google Drive OAuth (backend/data/secrets/gdrive_oauth_*.json on prod,
#     or .cursor/gcp-oauth.keys.json + gdrive-server-credentials.json locally)
#   node + scripts/gdrive/node_modules (googleapis)
#
# Environment (optional):
#   AUTO_BACKUP_FORCE=1        skip the Eastern 01:00 gate (manual / catch-up)
#   AUTO_BACKUP_SKIP_DO=1      skip droplet snapshot
#   AUTO_BACKUP_SKIP_DB=1      skip DB dump / Drive upload
#   AUTO_BACKUP_DRY_RUN=1      DO dry-run + Drive dry-run (no create/delete/upload)
#   DB_BACKUP_KEEP             default 14
#   DB_BACKUP_KEEP_LOCAL=1     keep local .sql.gz after successful upload (default: delete)
#
# Production crontab (server OS is UTC; CRON_TZ is NOT reliable on this host):
#   Fire every hour at :00 UTC; the script no-ops unless wall clock is 01:00 Eastern.
#     0 * * * * /opt/rec_io_server/scripts/cron/do_auto_backup_snapshot.sh
#
# That hits 01:00 America/New_York in both EDT (05:00 UTC) and EST (06:00 UTC),
# one hour after the bookkeeper 00:30 ET job.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV_PY="${REPO_ROOT}/venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  VENV_PY="$(command -v python3 || true)"
fi
if [[ -z "${VENV_PY}" || ! -x "$VENV_PY" ]]; then
  echo "do_auto_backup_snapshot: no python interpreter found" >&2
  exit 1
fi

NODE_BIN="$(command -v node || true)"
if [[ -z "${NODE_BIN}" ]]; then
  NODE_BIN="$(command -v nodejs || true)"
fi

# Always Eastern for gate and log stamps (server OS may be UTC).
export TZ="${TZ:-America/New_York}"

# Gate: only the real Eastern 01:00 tick runs. Hourly cron + this check replaces
# CRON_TZ (ignored on this droplet).
if [[ "${AUTO_BACKUP_FORCE:-}" != "1" ]]; then
  et_hm="$(TZ=America/New_York date '+%H:%M')"
  if [[ "$et_hm" != "01:00" ]]; then
    exit 0
  fi
fi

LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/do_auto_backup_snapshot.log"
TS_TZ="${AUTO_BACKUP_LOG_TZ:-America/New_York}"

run_do_snapshot() {
  if [[ "${AUTO_BACKUP_SKIP_DO:-}" == "1" ]]; then
    echo "skipping DigitalOcean snapshot (AUTO_BACKUP_SKIP_DO=1)"
    return 0
  fi
  echo "--- DigitalOcean auto_backup snapshot ---"
  "$VENV_PY" "${REPO_ROOT}/scripts/do/auto_backup_snapshot.py"
}

run_db_backup() {
  if [[ "${AUTO_BACKUP_SKIP_DB:-}" == "1" ]]; then
    echo "skipping DB backup / Drive upload (AUTO_BACKUP_SKIP_DB=1)"
    return 0
  fi
  echo "--- Postgres compressed dump + Google Drive DB_BACKUPS ---"
  if [[ -z "${NODE_BIN}" ]]; then
    echo "do_auto_backup_snapshot: node not found (required for Drive upload)" >&2
    return 1
  fi
  if [[ ! -d "${REPO_ROOT}/scripts/gdrive/node_modules/googleapis" ]]; then
    echo "do_auto_backup_snapshot: missing scripts/gdrive/node_modules (run npm install there)" >&2
    return 1
  fi

  local dump_out dump_path
  if [[ "${AUTO_BACKUP_DRY_RUN:-}" == "1" ]]; then
    echo "DRY_RUN: would create compressed DB dump and upload to Drive"
    "$NODE_BIN" "${REPO_ROOT}/scripts/gdrive/upload-db-backup.js" --prune-only --dry-run
    return 0
  fi

  dump_out="$(bash "${REPO_ROOT}/scripts/backup/create_compressed_db_backup.sh")"
  printf '%s\n' "$dump_out"
  dump_path="$(printf '%s\n' "$dump_out" | tail -n 1)"
  if [[ -z "$dump_path" || ! -f "$dump_path" ]]; then
    echo "do_auto_backup_snapshot: DB dump path missing or not a file: ${dump_path:-<empty>}" >&2
    return 1
  fi
  echo "uploading $dump_path to Drive DB_BACKUPS"
  "$NODE_BIN" "${REPO_ROOT}/scripts/gdrive/upload-db-backup.js" --file "$dump_path"

  if [[ "${DB_BACKUP_KEEP_LOCAL:-}" == "1" ]]; then
    echo "keeping local dump (DB_BACKUP_KEEP_LOCAL=1): $dump_path"
  else
    rm -f "$dump_path"
    echo "removed local dump after upload: $dump_path"
  fi
}

{
  echo "=== $(TZ="$TS_TZ" date '+%Y-%m-%d %H:%M:%S %Z') ==="
  run_do_snapshot
  run_db_backup
  echo "nightly backup: done"
  echo ""
} >>"$LOG_FILE" 2>&1
