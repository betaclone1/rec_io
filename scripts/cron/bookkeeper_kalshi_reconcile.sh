#!/usr/bin/env bash
# Nightly QuickBooks vs Kalshi reconcile (posts JournalEntry when gap >= --min-diff).
#
# Prereqs: same as manual run — user credentials under
#   backend/data/users/user_NNNN/credentials/quickbooks/.env
#   backend/data/users/user_NNNN/credentials/kalshi-credentials/prod
#
# Environment (optional):
#   REC_USER_NO          default 0001
#   BOOKKEEPER_FORCE=1   skip the Eastern 00:30 gate (manual / catch-up runs)
#
# Production crontab (server OS is UTC; CRON_TZ is NOT reliable on this host):
#   Fire every hour at :30 UTC; the script no-ops unless wall clock is 00:30 Eastern.
#     30 * * * * REC_USER_NO=0001 /opt/rec_io_server/scripts/cron/bookkeeper_kalshi_reconcile.sh
#
# That hits 00:30 America/New_York in both EDT (04:30 UTC) and EST (05:30 UTC).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

VENV_PY="${REPO_ROOT}/venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "bookkeeper_kalshi_reconcile: missing $VENV_PY" >&2
  exit 1
fi

export REC_USER_NO="${REC_USER_NO:-0001}"
# Always Eastern for log stamps and Python calendar helpers (server OS may be UTC).
export TZ="${TZ:-America/New_York}"

# Gate: only the real Eastern 00:30 tick posts. Hourly cron + this check replaces
# CRON_TZ (ignored on this droplet — jobs were firing at 00:30 UTC / 20:30 ET).
if [[ "${BOOKKEEPER_FORCE:-}" != "1" ]]; then
  et_hm="$(TZ=America/New_York date '+%H:%M')"
  if [[ "$et_hm" != "00:30" ]]; then
    exit 0
  fi
fi

LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/bookkeeper_kalshi_reconcile.log"
TS_TZ="${BOOKKEEPER_LOG_TZ:-America/New_York}"

{
  echo "=== $(TZ="$TS_TZ" date '+%Y-%m-%d %H:%M:%S %Z') | REC_USER_NO=${REC_USER_NO} ==="
  # --reconcile-prior-day: just after midnight ET → reconcile the just-closed day
  #   so interest/incentive credits land on their own calendar date.
  # Idempotent: skips if a reconcile JE already exists for that date (unless --force).
  "$VENV_PY" -m backend.bookkeeper.bookkeeper --user-no "$REC_USER_NO" \
    --reconcile-kalshi --reconcile-prior-day
  echo ""
} >>"$LOG_FILE" 2>&1
