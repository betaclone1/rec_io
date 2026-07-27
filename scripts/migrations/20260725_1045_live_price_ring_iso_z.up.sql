-- Ring timestamps: ISO-8601 UTC with Z suffix (YYYY-MM-DDTHH:MM:SS.mmmZ).
-- Truncate bare-UTC / prior-format rows so the ring is not mixed.

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
    EXECUTE format('TRUNCATE TABLE live_data.%I', tbl);
    EXECUTE format(
      'COMMENT ON COLUMN live_data.%I.timestamp IS %L',
      tbl,
      'CFB data.time as ISO-8601 UTC YYYY-MM-DDTHH:MM:SS.mmmZ'
    );
  END LOOP;
END
$$;
