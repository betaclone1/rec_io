ALTER TABLE live_data.market_kalshi_15m
  DROP COLUMN IF EXISTS yes_bid,
  DROP COLUMN IF EXISTS yes_ask,
  DROP COLUMN IF EXISTS no_bid,
  DROP COLUMN IF EXISTS no_ask,
  DROP COLUMN IF EXISTS last_price,
  DROP COLUMN IF EXISTS volume_24h_fp,
  DROP COLUMN IF EXISTS liquidity;
