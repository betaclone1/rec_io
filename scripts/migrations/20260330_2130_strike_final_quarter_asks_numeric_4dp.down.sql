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
    ) AND EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'live_data' AND table_name = t AND column_name = 'yes_ask_min_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I
           ALTER COLUMN yes_ask_min_15m TYPE NUMERIC(18,8) USING yes_ask_min_15m::numeric,
           ALTER COLUMN yes_ask_max_15m TYPE NUMERIC(18,8) USING yes_ask_max_15m::numeric,
           ALTER COLUMN no_ask_min_15m TYPE NUMERIC(18,8) USING no_ask_min_15m::numeric,
           ALTER COLUMN no_ask_max_15m TYPE NUMERIC(18,8) USING no_ask_max_15m::numeric,
           ALTER COLUMN yes_ask_range_15m TYPE NUMERIC(18,8) USING yes_ask_range_15m::numeric,
           ALTER COLUMN no_ask_range_15m TYPE NUMERIC(18,8) USING no_ask_range_15m::numeric;',
        t
      );
    END IF;
  END LOOP;
END $$;
