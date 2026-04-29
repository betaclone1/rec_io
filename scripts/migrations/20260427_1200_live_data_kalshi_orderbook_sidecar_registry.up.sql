-- Registry for Kalshi per-market orderbook tables maintained by market_watchdog_ws sidecar.
-- Physical tables are created lazily as live_data."orderbook_kalshi_<sanitized_ticker>"; this table tracks them for prune/drop.

CREATE SCHEMA IF NOT EXISTS live_data;

CREATE TABLE IF NOT EXISTS live_data.kalshi_orderbook_sidecar_registry (
    market_ticker TEXT PRIMARY KEY,
    table_name TEXT NOT NULL,
    market_interval TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kalshi_ob_sidecar_registry_interval
    ON live_data.kalshi_orderbook_sidecar_registry (market_interval);
