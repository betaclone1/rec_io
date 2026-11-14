-- Persist tails UI scores on the tracked-assets roster.
-- lower_tail_score / upper_tail_score match the win-rate chart badge:
--   round((30d_win_rate_pct - baseline) * 100) with baseline 1% (LT) / 99% (UT).
-- Written by the same path that refreshes historical_data.tail_backtest_rolling_rates.

ALTER TABLE live_data.symbols_list
  ADD COLUMN IF NOT EXISTS lower_tail_score INTEGER;

ALTER TABLE live_data.symbols_list
  ADD COLUMN IF NOT EXISTS upper_tail_score INTEGER;

COMMENT ON COLUMN live_data.symbols_list.lower_tail_score IS
  'Tails UI Lower Tail score from latest 30d exact-cent WR: round((wr_pct - 1) * 100). NULL if unknown. Updated with tail_backtest_rolling_rates.';

COMMENT ON COLUMN live_data.symbols_list.upper_tail_score IS
  'Tails UI Upper Tail score from latest 30d exact-cent WR: round((wr_pct - 99) * 100). NULL if unknown. Updated with tail_backtest_rolling_rates.';
