#!/usr/bin/env bash
# Stop processes started by cfb_test_ui_stack.sh (and free port 3000).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

supervisorctl -c "$ROOT/backend/supervisord.conf" shutdown 2>/dev/null || true
pkill -f "$ROOT/backend/redis_switchboard.py" 2>/dev/null || true
pkill -f "$ROOT/backend/main.py" 2>/dev/null || true
pkill -f "$ROOT/backend/symbol_price_watchdog.py" 2>/dev/null || true
pkill -f "$ROOT/backend/cfbenchmarks_price_watchdog.py" 2>/dev/null || true
lsof -ti :3000 2>/dev/null | xargs kill -9 2>/dev/null || true
echo "CFB test stack stopped."
