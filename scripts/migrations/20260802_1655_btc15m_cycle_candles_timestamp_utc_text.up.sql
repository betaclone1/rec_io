-- Align btc15m_cycle_candles.timestamp with cycle price_ring convention:
-- UTC ISO-Z TEXT (e.g. 2026-08-02T04:00:00.000Z), not timestamptz.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'historical_data'
      AND table_name = 'btc15m_cycle_candles'
      AND column_name = 'timestamp'
      AND data_type = 'timestamp with time zone'
  ) THEN
    ALTER TABLE historical_data.btc15m_cycle_candles
      ALTER COLUMN "timestamp" TYPE TEXT
      USING to_char(
        ("timestamp" AT TIME ZONE 'UTC'),
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
      );
  END IF;
END
$$;

COMMENT ON COLUMN historical_data.btc15m_cycle_candles."timestamp" IS
  'Cycle settlement end as UTC ISO-Z TEXT, e.g. 2026-08-02T04:00:00.000Z (matches historical_data.*_price_ring).';
