-- CFB windowed averages on live_price_ring_90m_*: trailing 60s + optional 15m final-minute avg.
-- Values are the numeric .value from Kalshi avg_60s_data / last_60s_windowed_average_15min.
-- Precision matches each table's existing price column.

DO $$
DECLARE
  tbl text;
  prec int;
  scale int;
  typ text;
BEGIN
  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'live_data'
      AND t.table_name LIKE 'live_price_ring_90m_%'
    ORDER BY 1
  LOOP
    SELECT c.numeric_precision, c.numeric_scale
      INTO prec, scale
    FROM information_schema.columns c
    WHERE c.table_schema = 'live_data'
      AND c.table_name = tbl
      AND c.column_name = 'price';

    IF prec IS NULL THEN
      typ := 'NUMERIC';
    ELSE
      typ := format('NUMERIC(%s,%s)', prec, COALESCE(scale, 0));
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'avg_60s'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I ADD COLUMN avg_60s %s',
        tbl, typ
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'last_60s_windowed_average_15min'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I ADD COLUMN last_60s_windowed_average_15min %s',
        tbl, typ
      );
    END IF;

    EXECUTE format(
      'COMMENT ON COLUMN live_data.%I.avg_60s IS %L',
      tbl,
      'Kalshi cfbenchmarks_value avg_60s_data.value (trailing 60s index average).'
    );
    EXECUTE format(
      'COMMENT ON COLUMN live_data.%I.last_60s_windowed_average_15min IS %L',
      tbl,
      'Kalshi last_60s_windowed_average_15min.value; present only in final minute before :00/:15/:30/:45; NULL otherwise.'
    );
  END LOOP;
END
$$;
