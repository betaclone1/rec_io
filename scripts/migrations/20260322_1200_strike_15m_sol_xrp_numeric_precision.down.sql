-- Revert SOL/XRP 15m strike numeric widening (lossy for fractional strikes).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m_sol'
  ) THEN
    ALTER TABLE live_data.strike_table_15m_sol
      ALTER COLUMN current_price TYPE DECIMAL(10,2) USING round(current_price::numeric, 2),
      ALTER COLUMN buffer TYPE DECIMAL(10,2) USING round(buffer::numeric, 2),
      ALTER COLUMN buffer_pct TYPE DECIMAL(5,2) USING round(buffer_pct::numeric, 2),
      ALTER COLUMN strike TYPE INTEGER USING round(strike)::integer;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m_xrp'
  ) THEN
    ALTER TABLE live_data.strike_table_15m_xrp
      ALTER COLUMN current_price TYPE DECIMAL(10,2) USING round(current_price::numeric, 2),
      ALTER COLUMN buffer TYPE DECIMAL(10,2) USING round(buffer::numeric, 2),
      ALTER COLUMN buffer_pct TYPE DECIMAL(5,2) USING round(buffer_pct::numeric, 2),
      ALTER COLUMN strike TYPE INTEGER USING round(strike)::integer;
  END IF;
END $$;
