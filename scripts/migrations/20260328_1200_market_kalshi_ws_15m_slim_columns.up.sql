-- WS 15m table: dollar-quote-only row; fixed-point open_interest as text; drop unused columns.

ALTER TABLE live_data.market_kalshi_ws_15m
    DROP COLUMN IF EXISTS volume_24h_fp,
    DROP COLUMN IF EXISTS yes_bid,
    DROP COLUMN IF EXISTS yes_ask,
    DROP COLUMN IF EXISTS no_bid,
    DROP COLUMN IF EXISTS no_ask,
    DROP COLUMN IF EXISTS last_price,
    DROP COLUMN IF EXISTS open_interest,
    DROP COLUMN IF EXISTS liquidity;

ALTER TABLE live_data.market_kalshi_ws_15m
    ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;
