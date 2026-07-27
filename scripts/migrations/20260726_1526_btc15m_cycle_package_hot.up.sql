-- BTC 15m cycle package hot tables live in historical_data (dynamic per-ticker).
-- Ensures schema + filesystem package root convention doc via comment.
-- Per-ticker tables are created at runtime by backend/core/cycle_hot_tables.py:
--   "{TICKER}_snapshot", "_deltas", "_strike_table", "_price_ring", "_metrics_ring"
-- Packages land under backend/data/historical_data/backtesting_data/KXBTC15M/{YYYY}/{YYYY_MM_MON}/

CREATE SCHEMA IF NOT EXISTS historical_data;

COMMENT ON SCHEMA historical_data IS
  'Historical / backtest warehouse. Includes strike_table_master partitions and '
  'ephemeral per-ticker BTC 15m cycle hot tables (KXBTC15M-*) prior to hourly packaging.';
