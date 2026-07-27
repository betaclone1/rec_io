-- Drop CFB windowed-average columns from live_price_ring_90m_*.

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'live_data'
      AND t.table_name LIKE 'live_price_ring_90m_%'
    ORDER BY 1
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'last_60s_windowed_average_15min'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I DROP COLUMN last_60s_windowed_average_15min',
        tbl
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'avg_60s'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I DROP COLUMN avg_60s',
        tbl
      );
    END IF;
  END LOOP;
END
$$;
