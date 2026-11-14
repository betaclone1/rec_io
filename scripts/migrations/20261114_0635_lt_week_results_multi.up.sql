-- Multi-asset LT week results (SOL/XRP/GOLD/SILVER/WTI, etc.) for live-vs-BT checks.
-- BTC/ETH keep dedicated tables; this holds the other series.

CREATE SCHEMA IF NOT EXISTS historical_data;

CREATE TABLE IF NOT EXISTS historical_data.lt_week_results (
    symbol TEXT NOT NULL,
    ticker TEXT NOT NULL,
    fill_time TIMESTAMP WITHOUT TIME ZONE,
    side TEXT,
    result TEXT,
    win_loss BOOLEAN,
    PRIMARY KEY (symbol, ticker)
);

CREATE INDEX IF NOT EXISTS idx_lt_week_results_symbol
  ON historical_data.lt_week_results (symbol);

COMMENT ON TABLE historical_data.lt_week_results IS
  'Per-ticker LT week slice by symbol from *_tail_backtest_cycles (exact-cent tape).';
