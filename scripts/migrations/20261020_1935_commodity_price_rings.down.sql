DO $$
DECLARE
  sym text;
BEGIN
  FOREACH sym IN ARRAY ARRAY['gold', 'silver', 'wti']
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS live_data.%I', 'live_price_ring_90m_' || sym);
  END LOOP;
END $$;
