# DB schema (brain summary)

## Connection (read-only for PM)

- **Config:** backend/core/config/database.py uses DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT (defaults: localhost, rec_io_db, rec_io_user, rec_io_password, 5432).
- **Scripts:** Load .env (and .env.postgresql); if REC_DB_* set and DB_* unset, set DB_* from REC_DB_* (REC_DB_PASS → DB_PASSWORD). Then get_postgresql_connection() or get_database_config().
- **Python one-liner:** PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import get_postgresql_connection; conn = get_postgresql_connection(); ..."

## Schemas (from live introspection)

- **users** — trades_0001, trades_simulated_0001, active_trades_0001, monitor_list_0001, strategy_list_0001, account_history_0001, fills_0001, orders_0001, positions_0001, settlements_0001, trade_history_preferences_0001, dashboard_preferences_0001, user_info_0001, transfers_0001, master_users, subaccounts_0001, trade_preferences_0001, trade_logs_0001; per-monitor active_trades_0001_10xxx, monitor_cycle_performance_0001_10xxx.
- **live_data** — live_price_log_1s_btc/eth/spx/ndx, live_symbol_status, strike_table_hourly_btc/eth/spx/ndx, strike_table_15m_btc/eth, market_kalshi_hourly_*, market_kalshi_15m_btc/eth, price_change_*, btc/eth_price_change, eth_price_log, symbols_list.
- **historical_data** — btc/eth/ndx/spx_price_history.
- **analytics** — probability_lookup_*_master_*, *_fingerprint_* (btc/eth/spx/ndx, ±10..±90), *_movement_profile_*, *_momentum_profile_*, *_price_profile_*, *_volatility_profile_*.
- **system** — health_status, installation_access_log.
- **archive** — monitor_cycle_performance_0001_10xxx (archived); **core** — system_state; **work_progress** — ttc_progress*, ttc_00xx_btc; **testing** — kalshi_* (orderbook/snapshot/deltas, etc.); **public** — active_trades, fills, positions, trades (legacy?).

## Critical tables for runtime

- users.trades_0001 — live trades.
- users.trades_simulated_0001 — simulated 15m trades (same shape, nullable buy_price/position/fees/bankroll/price_spread/sell_price).
- users.monitor_list_0001 — monitors (id 10xxx), strategy, auto_trade, market (hourly/15m), etc.
- users.strategy_list_0001 — strategy defaults.
- live_data.strike_table_hourly_*, strike_table_15m_* — ttc_hourly, ttc_15m, probability_hourly, probability_15m.
- live_data.live_price_log_1s_* — 1s price/momentum/delta/move; used for symbol_close on expiration.
- live_data.live_symbol_status — one row per symbol (latest tick).

## Init and migrations

- init_database() in backend/core/config/database.py creates schemas, tables, columns (IF NOT EXISTS / DO $$ ALTER ADD COLUMN). Single place for schema evolution. Run from project root: PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()".
- Full reference: docs/MASTER_DB_SCHEMA_REFERENCE.md. After portfolio table changes: run kalshi_historical_ingest once per changelog.
