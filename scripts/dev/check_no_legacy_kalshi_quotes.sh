#!/usr/bin/env bash
# Fail if bare cent-style bid/ask identifiers appear outside allowlisted Kalshi wire parsers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Files that legitimately reference Kalshi API JSON keys yes_bid / yes_ask (cents on the wire).
ALLOWLIST_REGEX='test_market_ticker_websocket\.py|kalshi_websocket_watchdog\.py'

matches="$(
  find backend frontend scripts/backtest \( -name '*.py' -o -name '*.js' -o -name '*.html' \) -print0 \
    | xargs -0 grep -nE '\b(yes_ask|no_ask|yes_bid|no_bid)\b' 2>/dev/null \
    | grep -vE 'yes_ask_dollars|no_ask_dollars|yes_bid_dollars|no_bid_dollars|yes_ask_min_15m|yes_ask_max_15m|no_ask_min_15m|no_ask_max_15m|yes_ask_range_15m|no_ask_range_15m|best_yes_bid|best_yes_ask|best_no_bid|best_no_ask|y_bid_cents|y_ask_cents' \
    | grep -vE "$ALLOWLIST_REGEX" \
    || true
)"

if [[ -n "${matches// }" ]]; then
  echo "$matches"
  echo "check_no_legacy_kalshi_quotes: disallowed bare yes_ask/no_ask/yes_bid/no_bid (use *_dollars / Kalshi wire allowlist)." >&2
  exit 1
fi

echo "check_no_legacy_kalshi_quotes: OK"
