-- Align with historical_data.*_price_history: naive US Eastern wall clock (America/New_York).

ALTER TABLE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99"
    ADD COLUMN IF NOT EXISTS "timestamp" TIMESTAMP WITHOUT TIME ZONE;

UPDATE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99"
SET "timestamp" = (to_timestamp(end_period_ts) AT TIME ZONE 'America/New_York')
WHERE "timestamp" IS NULL;

ALTER TABLE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99"
    ALTER COLUMN "timestamp" SET NOT NULL;

COMMENT ON COLUMN testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99"."timestamp" IS
    'Bar end instant as US Eastern wall time, no TZ (same convention as historical_data.btc_price_history.timestamp).';
