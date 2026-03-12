# DB schema (memory summary)

## Connection (read-only for PM)

- **Config:** backend/core/config/database.py uses DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT. If unset, falls back to REC_DB_HOST, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_PORT (single place for both conventions).
- **Scripts:** Use get_postgresql_connection() or get_database_config() from backend.core.config.database. Do not use POSTGRES_* or hardcoded credentials.
- **Python one-liner:** PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import get_postgresql_connection; conn = get_postgresql_connection(); ..."

## Schemas (from live introspection)

- **users** — trades_0001, trades_simulated_0001, active_trades_0001, monitor_list_0001, strategy_list_0001, account_history_0001, fills_0001, orders_0001, positions_0001, settlements_0001, trade_history_preferences_0001, dashboard_preferences_0001, user_info_0001, transfers_0001, master_users, subaccounts_0001, trade_preferences_0001, trade_logs_0001; per-monitor active_trades_0001_10xxx, monitor_cycle_performance_0001_10xxx.
- **live_data** — live_price_log_1s_btc/eth/spx/ndx, live_symbol_status, strike_table_hourly_btc/eth/spx/ndx, strike_table_15m_btc/eth, market_kalshi_hourly_* (volume_fp/volume_24h_fp), market_kalshi_15m_btc/eth (volume_fp/volume_24h_fp), price_change_*, btc/eth_price_change, eth_price_log, symbols_list.
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

- init_database() in backend/core/config.database.py creates schemas, tables, columns (IF NOT EXISTS / DO $$ ALTER ADD COLUMN). Single place for schema evolution. Run from project root: PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()".
- Full reference: docs/MASTER_DB_SCHEMA_REFERENCE.md. After portfolio table changes: run kalshi_historical_ingest once per changelog.
- Drift check: scripts/db/check_db_schema_drift.py fails if database.py table definitions differ from the reference doc for critical tables (trades_0001, trades_simulated_0001, monitor_list_0001, strategy_list_0001). Audit findings: docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md.
- account_history_0001: has kalshi_id (unique), vendor, rail (migration 20260307_1600_account_history_vendor_rail_kalshi_id). Sync uses Kalshi /deposits and /withdrawals; upsert by kalshi_id.

## Reversible migrations (apply / revert)

- **Convention:** Every schema or destructive data change is a migration pair in scripts/migrations/: `YYYYMMDD_HHMM_slug.up.sql` and `.down.sql`. Applied migrations tracked in system.schema_migrations.
- **Runner:** scripts/db/run_migration.py — `list` | `up [id]` | `down <id>`. Uses get_postgresql_connection() (DB_* env). See .cursor/pm/DB_REVERSIBLE_MIGRATIONS.md.
- **PG expert agent:** Must create up+down for any schema change; apply/revert via run_migration.py; no ad hoc DDL without a migration. Enables reverting DB changes similarly to reverting code.
