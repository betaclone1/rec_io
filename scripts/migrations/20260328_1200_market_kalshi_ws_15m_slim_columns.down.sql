-- Restore pre-slim column set for market_kalshi_ws_15m.

ALTER TABLE live_data.market_kalshi_ws_15m
    DROP COLUMN IF EXISTS open_interest_fp;

ALTER TABLE live_data.market_kalshi_ws_15m
    ADD COLUMN IF NOT EXISTS volume_24h_fp INTEGER,
    ADD COLUMN IF NOT EXISTS yes_bid INTEGER,
    ADD COLUMN IF NOT EXISTS yes_ask INTEGER,
    ADD COLUMN IF NOT EXISTS no_bid INTEGER,
    ADD COLUMN IF NOT EXISTS no_ask INTEGER,
    ADD COLUMN IF NOT EXISTS last_price INTEGER,
    ADD COLUMN IF NOT EXISTS open_interest INTEGER,
    ADD COLUMN IF NOT EXISTS liquidity INTEGER;
