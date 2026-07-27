-- Comment-only down; truncated rows cannot be restored.

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
    EXECUTE format(
      'COMMENT ON COLUMN live_data.%I.timestamp IS %L',
      tbl,
      'CFB data.time as UTC wall clock YYYY-MM-DDTHH:MM:SS[.mmm] (no TZ suffix).'
    );
  END LOOP;
END
$$;
