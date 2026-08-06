-- Reverse TEXT → timestamptz only when currently TEXT (best-effort).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'historical_data'
      AND table_name = 'btc15m_cycle_candles'
      AND column_name = 'timestamp'
      AND data_type = 'text'
  ) THEN
    ALTER TABLE historical_data.btc15m_cycle_candles
      ALTER COLUMN "timestamp" TYPE TIMESTAMPTZ
      USING ("timestamp"::timestamptz);
  END IF;
END
$$;

COMMENT ON COLUMN historical_data.btc15m_cycle_candles."timestamp" IS
  'Cycle settlement end instant in UTC (matches ticker Eastern end converted to UTC).';
