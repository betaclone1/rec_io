#!/usr/bin/env bash
# Minimal stack for /cfbenchmarks_feed_test (experiment UI) or live_state cutover dry-run.
# Full trading stack: use MASTER_RESTART (supervisor includes cfbenchmarks_price_watchdog only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/venv/bin/python"
export REC_PROJECT_ROOT="$ROOT"
export PYTHONPATH="$ROOT"
export REC_POOL_USER_NUMBER="${REC_POOL_USER_NUMBER:-0001}"
export REC_ENVIRONMENT="${REC_ENVIRONMENT:-development}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export LIVE_STATE_CACHE_ENABLED="${LIVE_STATE_CACHE_ENABLED:-1}"
export LIVE_STATE_USE_TICK_BUFFER="${LIVE_STATE_USE_TICK_BUFFER:-1}"
export REC_DB_HOST="${REC_DB_HOST:-localhost}"
export REC_DB_NAME="${REC_DB_NAME:-rec_io_db}"
export REC_DB_USER="${REC_DB_USER:-rec_io_user}"
export REC_DB_PASS="${REC_DB_PASS:-rec_io_password}"
export REC_DB_PORT="${REC_DB_PORT:-5432}"
export REC_DB_SSLMODE="${REC_DB_SSLMODE:-disable}"
export CFBENCHMARKS_INDEX_IDS="${CFBENCHMARKS_INDEX_IDS:-BRTI,ETHUSD_RTI,SOLUSD_RTI,XRPUSD_RTI,DOGEUSD_RTI}"
export CFBENCHMARKS_RING_PG="${CFBENCHMARKS_RING_PG:-1}"
export CFBENCHMARKS_PUBLISH_MODE="${CFBENCHMARKS_PUBLISH_MODE:-experiment}"
mkdir -p logs

if ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
  echo "Redis not responding at $REDIS_HOST:$REDIS_PORT — start Redis first."
  exit 1
fi

start_one() {
  local name="$1"
  shift
  if pgrep -f "$ROOT.*$1" >/dev/null 2>&1; then
    echo "already running: $name"
    return 0
  fi
  echo "starting $name"
  nohup "$PY" "$@" >>"logs/${name}.out.log" 2>>"logs/${name}.err.log" &
}

start_one redis_switchboard "$ROOT/backend/redis_switchboard.py"
start_one main_app "$ROOT/backend/main.py"
if [ "${CFB_TEST_LEGACY_COINBASE:-0}" = "1" ]; then
  for sym in BTC ETH SOL XRP; do
    start_one "symbol_price_watchdog_$(echo "$sym" | tr '[:upper:]' '[:lower:]')" \
      "$ROOT/backend/symbol_price_watchdog.py" "$sym"
  done
fi
start_one cfbenchmarks_price_watchdog "$ROOT/backend/cfbenchmarks_price_watchdog.py"

sleep 3
if curl -sf -o /dev/null "http://127.0.0.1:3000/cfbenchmarks_feed_test"; then
  echo "test UI: http://localhost:3000/cfbenchmarks_feed_test"
else
  echo "main_app not ready yet — check logs/main_app.err.log"
fi
echo "CFBENCHMARKS_PUBLISH_MODE=$CFBENCHMARKS_PUBLISH_MODE (set live_state for cutover; legacy WDs: CFB_TEST_LEGACY_COINBASE=1)"
