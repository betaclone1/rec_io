#!/usr/bin/env bash
# Monitor prod CFB feed + ring PG health for 2 hours after v3.9.1 deploy.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export REC_PROD_SSH_HOST="${REC_PROD_SSH_HOST:-165.22.13.146}"
SSH="./scripts/prod/rec_prod_ssh.sh"
OUT="$ROOT/tmp/cfb_monitor_2h_$(date -u +%Y%m%dT%H%M%SZ).log"
END=$(( $(date +%s) + 7200 ))
INTERVAL=120
echo "CFB 2h monitor start $(date -u +%Y-%m-%dT%H:%M:%SZ) end_unix=$END" | tee "$OUT"
echo "log=$OUT" | tee -a "$OUT"

sample() {
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  {
    echo ""
    echo "===== SAMPLE $ts ====="
  } | tee -a "$OUT"
  "$SSH" 'cd /opt/rec_io_server &&
    PID=$(ps -eo pid,args | awk "/backend\/cfbenchmarks_price_watchdog.py/ && !/awk/ {print \$1; exit}")
    echo "pid=$PID status=$(supervisorctl -c backend/supervisord.conf status cfbenchmarks_price_watchdog | awk "{print \$2}")"
    ps -p "$PID" -o pid=,pcpu=,etime=,rss= 2>/dev/null || echo "process missing"
    echo "-- threads --"
    for t in /proc/$PID/task/*/comm; do printf "%s " "$(cat $t 2>/dev/null)"; done; echo
    echo "-- last ticks (lag) --"
    grep "lag_kalshi_ms=" logs/cfbenchmarks_price_watchdog.out.log | tail -n 8
    echo "-- warnings/errors since restart window --"
    START_LINE=$(grep -n "starting cfbenchmarks watchdog mode=live_state" logs/cfbenchmarks_price_watchdog.out.log | tail -1 | cut -d: -f1)
    if [ -n "$START_LINE" ]; then
      tail -n +"$((START_LINE))" logs/cfbenchmarks_price_watchdog.out.log | grep -E "ERROR|WARNING|reconnect|dropped|queue full|fanout failed|batch failed|unhealthy|feed health" | tail -n 30 || true
      echo "(end warn scan)"
    else
      echo "(no start line)"
    fi
    echo "-- ring freshness (BTC/ETH latest ts) --"
    sudo -u postgres psql -d rec_io_db -tAc "
      SELECT '\''btc'\'' , max(timestamp) FROM live_data.live_price_ring_90m_btc
      UNION ALL SELECT '\''eth'\'', max(timestamp) FROM live_data.live_price_ring_90m_eth
      UNION ALL SELECT '\''btc_m'\'', max(timestamp) FROM live_data.live_metrics_ring_90m_btc
      UNION ALL SELECT '\''eth_m'\'', max(timestamp) FROM live_data.live_metrics_ring_90m_eth;
    " 2>/dev/null || echo "psql ring query failed"
  ' 2>&1 | tee -a "$OUT" || echo "SSH sample failed" | tee -a "$OUT"
}

while [ "$(date +%s)" -lt "$END" ]; do
  sample
  LAST_LAG=$(grep -oE "lag_kalshi_ms=[0-9]+" "$OUT" | tail -1 | cut -d= -f2 || true)
  if [ -n "${LAST_LAG:-}" ] && [ "$LAST_LAG" -gt 5000 ] 2>/dev/null; then
    echo "ALERT lag_kalshi_ms=$LAST_LAG > 5000ms at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$OUT"
  fi
  # Only alert on reconnect lines from the latest sample block (not prior history)
  if awk "/===== SAMPLE /{p=0} /===== SAMPLE $(date -u +%Y-%m-%dT%H)/{p=1} p" "$OUT" 2>/dev/null | grep -q "reconnect"; then
    echo "ALERT reconnect in latest window at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$OUT"
  fi
  REMAIN=$(( END - $(date +%s) ))
  echo "sleep ${INTERVAL}s remain=${REMAIN}s" | tee -a "$OUT"
  if [ "$REMAIN" -le 0 ]; then break; fi
  if [ "$REMAIN" -lt "$INTERVAL" ]; then sleep "$REMAIN"; else sleep "$INTERVAL"; fi
done

{
  echo ""
  echo "===== FINAL SUMMARY $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} | tee -a "$OUT"
RECONNECTS=$(grep -c "ALERT reconnect" "$OUT" || true)
DROPS=$(grep -cE "dropped|queue full|batch failed" "$OUT" || true)
ALERTS=$(grep -c "^ALERT " "$OUT" || true)
MAXLAG=$(grep -oE "lag_kalshi_ms=[0-9]+" "$OUT" | cut -d= -f2 | sort -n | tail -1 || true)
echo "reconnect_alerts=$RECONNECTS drop_mentions=$DROPS alerts=$ALERTS max_lag_seen_ms=${MAXLAG:-n/a}" | tee -a "$OUT"
sample
echo "DONE log=$OUT" | tee -a "$OUT"
