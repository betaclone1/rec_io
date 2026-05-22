-- YES fair in Kalshi dollar units: positive lookup leg / 100 (strike_table_generator INSERT only).

ALTER TABLE live_data.strike_table_15m
    ADD COLUMN IF NOT EXISTS fair_price NUMERIC(12, 8);

ALTER TABLE live_data.strike_table_hourly
    ADD COLUMN IF NOT EXISTS fair_price NUMERIC(12, 8);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_ws_15m'
    ) THEN
        EXECUTE 'ALTER TABLE live_data.strike_table_ws_15m ADD COLUMN IF NOT EXISTS fair_price NUMERIC(12, 8)';
    END IF;
END $$;
