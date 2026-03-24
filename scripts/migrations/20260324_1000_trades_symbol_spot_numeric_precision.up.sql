-- Widen trade spot columns so SOL/XRP (and other low-priced spots) persist at 5dp like strike tables.
-- trade_manager writes Decimal/NUMERIC via normalize_trade_spot_price.

ALTER TABLE users.trades_0001
  ALTER COLUMN symbol_open TYPE NUMERIC(18,5) USING symbol_open::numeric,
  ALTER COLUMN symbol_close TYPE NUMERIC(18,5) USING symbol_close::numeric;

ALTER TABLE users.trades_simulated_0001
  ALTER COLUMN symbol_open TYPE NUMERIC(18,5) USING symbol_open::numeric,
  ALTER COLUMN symbol_close TYPE NUMERIC(18,5) USING symbol_close::numeric;
