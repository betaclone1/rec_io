-- Restore prior per-symbol price widths (BTC/ETH 10,2; SOL/XRP/DOGE 10,6).
-- avg columns match the restored price width.

DO $$
DECLARE
  tbl text;
  typ text;
BEGIN
  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'live_data'
      AND t.table_name LIKE 'live_price_ring_90m_%'
    ORDER BY 1
  LOOP
    IF tbl IN (
      'live_price_ring_90m_btc',
      'live_price_ring_90m_eth'
    ) THEN
      typ := 'NUMERIC(10,2)';
    ELSE
      typ := 'NUMERIC(10,6)';
    END IF;

    EXECUTE format(
      'ALTER TABLE live_data.%I ALTER COLUMN price TYPE %s USING price::%s',
      tbl, typ, typ
    );
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'avg_60s'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I ALTER COLUMN avg_60s TYPE %s USING avg_60s::%s',
        tbl, typ, typ
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'live_data'
        AND c.table_name = tbl
        AND c.column_name = 'last_60s_windowed_average_15min'
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.%I ALTER COLUMN last_60s_windowed_average_15min TYPE %s
         USING last_60s_windowed_average_15min::%s',
        tbl, typ, typ
      );
    END IF;
  END LOOP;
END
$$;
