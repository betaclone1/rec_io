ALTER TABLE historical_data.btc15m_cycle_candles
  DROP COLUMN IF EXISTS market_result;

ALTER TABLE historical_data.btc15m_cycle_candles
  ALTER COLUMN total_range_pct TYPE NUMERIC(12, 6),
  ALTER COLUMN final_diff_pct TYPE NUMERIC(12, 6);
