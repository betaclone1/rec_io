-- symbol_price_watchdog insert_tick expects the same columns as BTC/ETH live 1s logs.
-- 20260320_2100 created SOL/XRP tables without momentum/volatility percentile columns.

ALTER TABLE live_data.live_price_log_1s_sol
  ADD COLUMN IF NOT EXISTS momentum_percentile DECIMAL(5,1),
  ADD COLUMN IF NOT EXISTS momentum_5s_avg DECIMAL(5,1),
  ADD COLUMN IF NOT EXISTS momentum_30s_avg DECIMAL(5,1),
  ADD COLUMN IF NOT EXISTS volatility DECIMAL(10,6),
  ADD COLUMN IF NOT EXISTS volatility_percentile DECIMAL(5,1);

ALTER TABLE live_data.live_price_log_1s_xrp
  ADD COLUMN IF NOT EXISTS momentum_percentile DECIMAL(5,1),
  ADD COLUMN IF NOT EXISTS momentum_5s_avg DECIMAL(5,1),
  ADD COLUMN IF NOT EXISTS momentum_30s_avg DECIMAL(5,1),
  ADD COLUMN IF NOT EXISTS volatility DECIMAL(10,6),
  ADD COLUMN IF NOT EXISTS volatility_percentile DECIMAL(5,1);
