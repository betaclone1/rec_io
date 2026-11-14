-- Per-ticker ETH Lower Tail results for week accuracy checks vs live.
-- Loaded from historical_data.kxeth15m_tail_backtest_cycles (exact-cent tape).

CREATE SCHEMA IF NOT EXISTS historical_data;

CREATE TABLE IF NOT EXISTS historical_data.eth_lt_week_results (
    ticker TEXT PRIMARY KEY,
    fill_time TIMESTAMP WITHOUT TIME ZONE,
    side TEXT,
    result TEXT,
    win_loss BOOLEAN
);

COMMENT ON TABLE historical_data.eth_lt_week_results IS
  'ETH LT per-ticker week slice from kxeth15m_tail_backtest_cycles (fill_time/side/result/win_loss).';
