-- Feed depth for each symbol, independent of category.
-- full: underlying price, internal metrics (momentum, probability, strike), orderbooks, public trades
-- market: underlying price plus lean market data (public trades, lifecycle, market meta); no orderbook or internal metrics
-- price_only: underlying price only
-- none: no live tracking
-- Changing the value is the switch. Pipelines re-read this column and move the symbol to that depth.

ALTER TABLE live_data.symbols_list
  ADD COLUMN IF NOT EXISTS live_data_level TEXT NOT NULL DEFAULT 'none';

UPDATE live_data.symbols_list
SET live_data_level = 'full'
WHERE UPPER(TRIM(symbol)) IN ('BTC', 'ETH');

UPDATE live_data.symbols_list
SET live_data_level = 'market'
WHERE UPPER(TRIM(symbol)) IN ('GOLD', 'SILVER', 'WTI');

UPDATE live_data.symbols_list
SET live_data_level = 'none'
WHERE UPPER(TRIM(symbol)) IN ('SOL', 'XRP', 'DOGE');

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'symbols_list_live_data_level_check'
      AND conrelid = 'live_data.symbols_list'::regclass
  ) THEN
    ALTER TABLE live_data.symbols_list
      ADD CONSTRAINT symbols_list_live_data_level_check
      CHECK (live_data_level IN ('full', 'market', 'price_only', 'none'));
  END IF;
END $$;

COMMENT ON COLUMN live_data.symbols_list.live_data_level IS
  'Live feed depth for this symbol: full, market, price_only, or none. Independent of category. Pipelines follow this value and switch when it changes.';

COMMENT ON COLUMN live_data.symbols_list.category IS
  'Asset class: crypto or commodity. Selects the price source family. Feed depth is live_data_level, not category.';
