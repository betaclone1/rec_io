-- Store CFB price / avg_60s / last_60s_windowed_average_15min at full Kalshi decimal
-- specificity (API formats averages to 8 decimal places; spot value as supplied).
-- Uniform NUMERIC(20,8) on all live_price_ring_90m_* tables (all symbols).

DO $$
DECLARE
  tbl text;
  col text;
BEGIN
  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'live_data'
      AND t.table_name LIKE 'live_price_ring_90m_%'
    ORDER BY 1
  LOOP
    FOREACH col IN ARRAY ARRAY[
      'price',
      'avg_60s',
      'last_60s_windowed_average_15min'
    ]
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'live_data'
          AND c.table_name = tbl
          AND c.column_name = col
      ) THEN
        EXECUTE format(
          'ALTER TABLE live_data.%I ALTER COLUMN %I TYPE NUMERIC(20,8)
           USING %I::numeric(20,8)',
          tbl, col, col
        );
      END IF;
    END LOOP;

    EXECUTE format(
      'COMMENT ON COLUMN live_data.%I.price IS %L',
      tbl,
      'CFB data.value at full API decimal specificity (NUMERIC(20,8)).'
    );
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'avg_60s'
    ) THEN
      EXECUTE format(
        'COMMENT ON COLUMN live_data.%I.avg_60s IS %L',
        tbl,
        'Kalshi avg_60s_data.value at full API specificity (NUMERIC(20,8)).'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'last_60s_windowed_average_15min'
    ) THEN
      EXECUTE format(
        'COMMENT ON COLUMN live_data.%I.last_60s_windowed_average_15min IS %L',
        tbl,
        'Kalshi last_60s_windowed_average_15min.value at full API specificity (NUMERIC(20,8)); NULL outside final minute.'
      );
    END IF;
  END LOOP;
END
$$;
