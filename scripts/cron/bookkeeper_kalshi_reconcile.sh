#!/usr/bin/env bash
# Nightly QuickBooks vs Kalshi reconcile (posts JournalEntry when gap >= --min-diff).
#
# Prereqs: same as manual run — user credentials under
#   backend/data/users/user_NNNN/credentials/quickbooks/.env
#   backend/data/users/user_NNNN/credentials/kalshi-credentials/prod
#
# Environment (optional):
#   REC_USER_NO   default 0001
#
# Crontab example (12:30 AM US Eastern wall clock, Linux cron with cronie):
#   CRON_TZ=America/New_York
#   30 0 * * * /opt/rec_io_server/scripts/cron/bookkeeper_kalshi_reconcile.sh
#
# If your cron does not support CRON_TZ, either set the server timezone to
# America/New_York or convert 12:30 AM Eastern to your server's local time.
# See docs/ARCHITECTURE.md (CRON_TZ, trading clock).

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
LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/bookkeeper_kalshi_reconcile.log"
TS_TZ="${BOOKKEEPER_LOG_TZ:-America/New_York}"

{
  echo "=== $(TZ="$TS_TZ" date '+%Y-%m-%d %H:%M:%S %Z') | REC_USER_NO=${REC_USER_NO} ==="
  "$VENV_PY" -m backend.bookkeeper.bookkeeper --user-no "$REC_USER_NO" --reconcile-kalshi
  echo ""
} >>"$LOG_FILE" 2>&1
