-- Price rings for every SYMBOL_CONFIG symbol whose price method is pyth.
-- Same shape as live_price_ring_90m_* after 20260725_1350_live_price_ring_full_precision.
-- avg_60s is the tick one_minute_avg (these feeds have no CFB avg_60s_data).
-- App resolves the table as live_data.live_price_ring_90m_{lower(symbol)}.

DO $$
DECLARE
  sym text;
BEGIN
  FOREACH sym IN ARRAY ARRAY['gold', 'silver', 'wti']
  LOOP
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS live_data.%I (
         timestamp TEXT PRIMARY KEY,
         price NUMERIC(20, 8) NOT NULL,
         avg_60s NUMERIC(20, 8),
         last_60s_windowed_average_15min NUMERIC(20, 8)
       )',
      'live_price_ring_90m_' || sym
    );
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON live_data.%I USING btree ("timestamp")',
      'idx_live_price_ring_90m_' || sym || '_timestamp',
      'live_price_ring_90m_' || sym
    );
    EXECUTE format(
      'COMMENT ON TABLE live_data.%I IS %L',
      'live_price_ring_90m_' || sym,
      'Pyth commodity sidecar: rolling ~90m ticks. avg_60s is one_minute_avg for symbol_close.'
    );
  END LOOP;
END $$;
