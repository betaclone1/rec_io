-- Per-ticker BTC Lower Tail results for week accuracy checks vs live.
-- Loaded from historical_data.kxbtc15m_tail_backtest_cycles (exact-cent tape).

CREATE SCHEMA IF NOT EXISTS historical_data;

CREATE TABLE IF NOT EXISTS historical_data.btc_lt_week_results (
    ticker TEXT PRIMARY KEY,
    fill_time TIMESTAMP WITHOUT TIME ZONE,
    side TEXT,
    result TEXT,
    win_loss BOOLEAN
);

COMMENT ON TABLE historical_data.btc_lt_week_results IS
  'BTC LT per-ticker week slice from kxbtc15m_tail_backtest_cycles (fill_time/side/result/win_loss).';
COMMENT ON COLUMN historical_data.btc_lt_week_results.fill_time IS
  'Eastern-naive first exact-cent LT public print (lt_fill_ts).';
COMMENT ON COLUMN historical_data.btc_lt_week_results.side IS
  'yes|no from lt_side.';
COMMENT ON COLUMN historical_data.btc_lt_week_results.result IS
  'Venue market_result yes|no.';
COMMENT ON COLUMN historical_data.btc_lt_week_results.win_loss IS
  'TRUE if lt_side matches market_result; NULL if no fill or unsettled.';
