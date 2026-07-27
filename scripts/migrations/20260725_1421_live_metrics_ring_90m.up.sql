-- Parallel 90m metrics ring: profile-tied hot-path percentiles for backtesting.
-- Same ISO-8601 UTC timestamp PK as live_price_ring_90m_* (join key).
-- Does not replace live_state; async sidecar only.

CREATE TABLE IF NOT EXISTS live_data.live_metrics_ring_90m_btc (
    timestamp TEXT PRIMARY KEY,
    momentum_percentile NUMERIC(8, 2),
    volatility_percentile NUMERIC(8, 2),
    movement_percentile NUMERIC(8, 2),
    momentum_5s_avg NUMERIC(8, 2),
    momentum_10s_avg NUMERIC(8, 2),
    momentum_30s_avg NUMERIC(8, 2),
    momentum_1m_avg NUMERIC(8, 2),
    momentum_acceleration NUMERIC(8, 2)
);

CREATE INDEX IF NOT EXISTS idx_live_metrics_ring_90m_btc_timestamp
    ON live_data.live_metrics_ring_90m_btc USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_metrics_ring_90m_eth (
    timestamp TEXT PRIMARY KEY,
    momentum_percentile NUMERIC(8, 2),
    volatility_percentile NUMERIC(8, 2),
    movement_percentile NUMERIC(8, 2),
    momentum_5s_avg NUMERIC(8, 2),
    momentum_10s_avg NUMERIC(8, 2),
    momentum_30s_avg NUMERIC(8, 2),
    momentum_1m_avg NUMERIC(8, 2),
    momentum_acceleration NUMERIC(8, 2)
);

CREATE INDEX IF NOT EXISTS idx_live_metrics_ring_90m_eth_timestamp
    ON live_data.live_metrics_ring_90m_eth USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_metrics_ring_90m_sol (
    timestamp TEXT PRIMARY KEY,
    momentum_percentile NUMERIC(8, 2),
    volatility_percentile NUMERIC(8, 2),
    movement_percentile NUMERIC(8, 2),
    momentum_5s_avg NUMERIC(8, 2),
    momentum_10s_avg NUMERIC(8, 2),
    momentum_30s_avg NUMERIC(8, 2),
    momentum_1m_avg NUMERIC(8, 2),
    momentum_acceleration NUMERIC(8, 2)
);

CREATE INDEX IF NOT EXISTS idx_live_metrics_ring_90m_sol_timestamp
    ON live_data.live_metrics_ring_90m_sol USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_metrics_ring_90m_xrp (
    timestamp TEXT PRIMARY KEY,
    momentum_percentile NUMERIC(8, 2),
    volatility_percentile NUMERIC(8, 2),
    movement_percentile NUMERIC(8, 2),
    momentum_5s_avg NUMERIC(8, 2),
    momentum_10s_avg NUMERIC(8, 2),
    momentum_30s_avg NUMERIC(8, 2),
    momentum_1m_avg NUMERIC(8, 2),
    momentum_acceleration NUMERIC(8, 2)
);

CREATE INDEX IF NOT EXISTS idx_live_metrics_ring_90m_xrp_timestamp
    ON live_data.live_metrics_ring_90m_xrp USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_metrics_ring_90m_doge (
    timestamp TEXT PRIMARY KEY,
    momentum_percentile NUMERIC(8, 2),
    volatility_percentile NUMERIC(8, 2),
    movement_percentile NUMERIC(8, 2),
    momentum_5s_avg NUMERIC(8, 2),
    momentum_10s_avg NUMERIC(8, 2),
    momentum_30s_avg NUMERIC(8, 2),
    momentum_1m_avg NUMERIC(8, 2),
    momentum_acceleration NUMERIC(8, 2)
);

CREATE INDEX IF NOT EXISTS idx_live_metrics_ring_90m_doge_timestamp
    ON live_data.live_metrics_ring_90m_doge USING btree ("timestamp");

COMMENT ON TABLE live_data.live_metrics_ring_90m_btc IS
    'Async CFB sidecar: profile-tied percentiles at each price-ring UTC tick for backtesting. Not on hot path.';
COMMENT ON TABLE live_data.live_metrics_ring_90m_eth IS
    'Async CFB sidecar: profile-tied percentiles at each price-ring UTC tick for backtesting. Not on hot path.';
COMMENT ON TABLE live_data.live_metrics_ring_90m_sol IS
    'Async CFB sidecar: profile-tied percentiles at each price-ring UTC tick for backtesting. Not on hot path.';
COMMENT ON TABLE live_data.live_metrics_ring_90m_xrp IS
    'Async CFB sidecar: profile-tied percentiles at each price-ring UTC tick for backtesting. Not on hot path.';
COMMENT ON TABLE live_data.live_metrics_ring_90m_doge IS
    'Async CFB sidecar: profile-tied percentiles at each price-ring UTC tick for backtesting. Not on hot path.';
