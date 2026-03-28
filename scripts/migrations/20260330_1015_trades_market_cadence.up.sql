-- Cadence for Kalshi contracts: hourly vs 15m (distinct from venue slug in `exchange`).
ALTER TABLE users.trades_0001 ADD COLUMN IF NOT EXISTS market VARCHAR(10);

ALTER TABLE users.trades_simulated_0001 ADD COLUMN IF NOT EXISTS market VARCHAR(10);

UPDATE users.trades_0001
SET market = '15m'
WHERE market IS NULL
  AND (
    LOWER(COALESCE(trade_strategy, '')) LIKE '%15m%'
    OR UPPER(COALESCE(ticker, '')) LIKE '%15M%'
  );

UPDATE users.trades_0001
SET market = 'hourly'
WHERE market IS NULL;

UPDATE users.trades_simulated_0001
SET market = '15m'
WHERE market IS NULL
  AND (
    LOWER(COALESCE(trade_strategy, '')) LIKE '%15m%'
    OR UPPER(COALESCE(ticker, '')) LIKE '%15M%'
  );

UPDATE users.trades_simulated_0001
SET market = 'hourly'
WHERE market IS NULL;
