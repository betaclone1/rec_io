-- SOL/XRP 15m strike rows: preserve sub-dollar price and buffer for probability/buffer math.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m_sol'
  ) THEN
    ALTER TABLE live_data.strike_table_15m_sol
      ALTER COLUMN current_price TYPE NUMERIC(18,5) USING round(current_price::numeric, 5),
      ALTER COLUMN buffer TYPE NUMERIC(18,5) USING round(buffer::numeric, 5),
      ALTER COLUMN buffer_pct TYPE NUMERIC(12,6) USING round(buffer_pct::numeric, 6),
      ALTER COLUMN strike TYPE NUMERIC(18,5) USING round(strike::numeric, 5);
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m_xrp'
  ) THEN
    ALTER TABLE live_data.strike_table_15m_xrp
      ALTER COLUMN current_price TYPE NUMERIC(18,5) USING round(current_price::numeric, 5),
      ALTER COLUMN buffer TYPE NUMERIC(18,5) USING round(buffer::numeric, 5),
      ALTER COLUMN buffer_pct TYPE NUMERIC(12,6) USING round(buffer_pct::numeric, 6),
      ALTER COLUMN strike TYPE NUMERIC(18,5) USING round(strike::numeric, 5);
  END IF;
END $$;
