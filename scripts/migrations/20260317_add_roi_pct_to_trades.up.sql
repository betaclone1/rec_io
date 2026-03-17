-- Add roi_pct (per-trade return on investment %, net fees) to trades tables

ALTER TABLE users.trades_0001
ADD COLUMN IF NOT EXISTS roi_pct REAL;

ALTER TABLE users.trades_simulated_0001
ADD COLUMN IF NOT EXISTS roi_pct REAL;

-- Backfill roi_pct for existing live trades where we have pnl, buy_price, and position.
-- Definition: roi_pct = (pnl / (buy_price * position)) * 100, using pnl net of fees.

UPDATE users.trades_0001
SET roi_pct = ROUND(((pnl / (buy_price * position)) * 100.0)::numeric, 5)
WHERE status IN ('closed', 'expired')
  AND pnl IS NOT NULL
  AND buy_price IS NOT NULL
  AND position IS NOT NULL
  AND (buy_price * position) > 0;

