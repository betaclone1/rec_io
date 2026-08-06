-- One row per KXBTC15M cycle: floor_strike as candle open, high/low/close from
-- Kalshi /live_data/events timeseries (same source as trade-history detail charts).

CREATE SCHEMA IF NOT EXISTS historical_data;

CREATE TABLE IF NOT EXISTS historical_data.btc15m_cycle_candles (
    "timestamp" TEXT NOT NULL,
    ticker TEXT NOT NULL,
    contract TEXT,
    floor_strike NUMERIC(18, 8),
    high_price NUMERIC(18, 8),
    low_price NUMERIC(18, 8),
    close NUMERIC(18, 8),
    total_range_pct NUMERIC(12, 6),
    final_diff_pct NUMERIC(12, 6),
    PRIMARY KEY (ticker)
);

COMMENT ON TABLE historical_data.btc15m_cycle_candles IS
  'Per KXBTC15M cycle candle: open=floor_strike; high/low/close from Kalshi live_data timeseries; '
  'timestamp is cycle settlement end as UTC ISO-Z TEXT (same convention as cycle price rings). Percents are vs floor_strike.';

COMMENT ON COLUMN historical_data.btc15m_cycle_candles."timestamp" IS
  'Cycle settlement end as UTC ISO-Z TEXT, e.g. 2026-08-02T04:00:00.000Z (matches historical_data.*_price_ring).';

COMMENT ON COLUMN historical_data.btc15m_cycle_candles.total_range_pct IS
  '(high_price - low_price) / floor_strike * 100';

COMMENT ON COLUMN historical_data.btc15m_cycle_candles.final_diff_pct IS
  '(close - floor_strike) / floor_strike * 100';

CREATE INDEX IF NOT EXISTS idx_btc15m_cycle_candles_timestamp
  ON historical_data.btc15m_cycle_candles ("timestamp");
