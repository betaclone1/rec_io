-- Rolling 7/30/90 trading-day LT/UT win rates + participation from cycle tables.
-- Refreshed by public_trades_drive_sync after each cycle upsert.

CREATE SCHEMA IF NOT EXISTS historical_data;

CREATE TABLE IF NOT EXISTS historical_data.tail_backtest_rolling_rates (
    series TEXT NOT NULL,
    as_of_trading_day DATE NOT NULL,
    window_trading_days INTEGER NOT NULL,
    lt_cycles INTEGER NOT NULL DEFAULT 0,
    lt_filled INTEGER NOT NULL DEFAULT 0,
    lt_scored INTEGER NOT NULL DEFAULT 0,
    lt_wins INTEGER NOT NULL DEFAULT 0,
    lt_win_rate NUMERIC(10, 6),
    lt_participation NUMERIC(10, 6),
    ut_cycles INTEGER NOT NULL DEFAULT 0,
    ut_filled INTEGER NOT NULL DEFAULT 0,
    ut_scored INTEGER NOT NULL DEFAULT 0,
    ut_wins INTEGER NOT NULL DEFAULT 0,
    ut_win_rate NUMERIC(10, 6),
    ut_participation NUMERIC(10, 6),
    trading_days_in_window INTEGER NOT NULL DEFAULT 0,
    trading_days_with_rows INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (series, as_of_trading_day, window_trading_days),
    CONSTRAINT tail_backtest_rolling_rates_window_chk
      CHECK (window_trading_days IN (7, 30, 90))
);

CREATE INDEX IF NOT EXISTS idx_tail_backtest_rolling_rates_as_of
  ON historical_data.tail_backtest_rolling_rates (as_of_trading_day);

CREATE INDEX IF NOT EXISTS idx_tail_backtest_rolling_rates_series_window
  ON historical_data.tail_backtest_rolling_rates (series, window_trading_days, as_of_trading_day DESC);

COMMENT ON TABLE historical_data.tail_backtest_rolling_rates IS
  '7/30/90 trading-day exact-cent LT/UT win rate and participation snapshots; '
  'derived from historical_data.*_tail_backtest_cycles; refreshed hourly.';

COMMENT ON COLUMN historical_data.tail_backtest_rolling_rates.lt_win_rate IS
  'lt_wins / lt_scored; NULL when lt_scored = 0 (no settled fills in window).';

COMMENT ON COLUMN historical_data.tail_backtest_rolling_rates.lt_participation IS
  'lt_filled / lt_cycles; NULL when lt_cycles = 0.';
