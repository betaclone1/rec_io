# 15m WS Cutover Runbook

This runbook switches 15m trading data consumers and producers to the WS pipeline, with a fast rollback path.

## Scope

- 15m strike read source in:
  - `backend/auto_entry_supervisor.py`
  - `backend/active_trade_supervisor.py`
- 15m market snapshot source in:
  - `backend/active_trade_supervisor.py`
- 15m producer programs in supervisor:
  - WS primary: `market_watchdog_ws_kalshi_15m`, `strike_table_generator_ws_15m`
  - Legacy standby: `market_watchdog_kalshi_15m`, `strike_table_generator_15m`

## Source Toggles

- `STRIKE_TABLE_15M_SOURCE`:
  - `ws` (default): use `live_data.strike_table_ws_15m`
  - `legacy`: use `live_data.strike_table_15m`
- `KALSHI_15M_MARKET_SOURCE`:
  - `ws` (default): use `live_data.market_kalshi_ws_15m`
  - `legacy`: use `live_data.market_kalshi_15m`
- `INCLUDE_LEGACY_15M_PIPELINE` (config generation only):
  - `0` (default): do not include legacy 15m producer services in generated supervisor config
  - `1`: include legacy 15m producer services

## Pre-Cutover Checks

1. Verify WS pipeline health rows exist and are fresh:
   - `SELECT exchange, symbol, pipeline_healthy, pipeline_health_reason, pipeline_health_checked_at FROM live_data.strike_pipeline_health_15m ORDER BY symbol;`
2. Run parity check:
   - `venv/bin/python3 scripts/diagnostics/check_15m_ws_parity.py --symbols BTC,ETH,SOL,XRP`
3. Confirm no persistent all-symbol degradation in dashboard power lights.

## Cutover Procedure

1. Ensure 15m consumers use WS sources (defaults already set in code):
   - `STRIKE_TABLE_15M_SOURCE=ws`
   - `KALSHI_15M_MARKET_SOURCE=ws`
2. Keep only WS 15m producers active:
   - `supervisorctl stop market_watchdog_kalshi_15m strike_table_generator_15m`
   - `supervisorctl start market_watchdog_ws_kalshi_15m strike_table_generator_ws_15m`
3. Restart 15m supervisors so read-path config is active:
   - `supervisorctl restart auto_entry_supervisor_15m active_trade_supervisor_15m`
4. Observe for at least 3 rollovers:
   - health freshness
   - trade initiation suppression during simulated outage
   - no prolonged false red across all 15m monitors

## Fast Rollback

1. Flip consumers back to legacy sources:
   - `STRIKE_TABLE_15M_SOURCE=legacy`
   - `KALSHI_15M_MARKET_SOURCE=legacy`
2. Restore legacy producers:
   - `supervisorctl start market_watchdog_kalshi_15m strike_table_generator_15m`
3. Restart 15m supervisors:
   - `supervisorctl restart auto_entry_supervisor_15m active_trade_supervisor_15m`
4. Optional: stop WS producers if needed:
   - `supervisorctl stop market_watchdog_ws_kalshi_15m strike_table_generator_ws_15m`

## Post-Cutover Validation

- Parity check passes for target symbols.
- No auto-entry initiation while pipeline unhealthy/stale.
- Auto-stop close initiation also blocked while unhealthy/stale.
- Monitor health endpoint reflects symbol-scoped states:
  - `GET /api/monitors/health`
