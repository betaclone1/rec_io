DO $$
DECLARE
  t TEXT;
  tables TEXT[] := ARRAY[
    'strike_table_15m',
    'strike_table_ws_15m',
    'strike_table_hourly_btc',
    'strike_table_hourly_eth',
    'strike_table_hourly_ndx',
    'strike_table_hourly_spx',
    'strike_table_15m_btc',
    'strike_table_15m_eth',
    'strike_table_15m_sol',
    'strike_table_15m_xrp'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'live_data' AND table_name = t
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I
           DROP COLUMN IF EXISTS yes_ask_min_15m,
           DROP COLUMN IF EXISTS yes_ask_max_15m,
           DROP COLUMN IF EXISTS no_ask_min_15m,
           DROP COLUMN IF EXISTS no_ask_max_15m,
           DROP COLUMN IF EXISTS yes_ask_range_15m,
           DROP COLUMN IF EXISTS no_ask_range_15m;',
        t
      );
    END IF;
  END LOOP;
END $$;
