ALTER TABLE live_data.strike_table_15m
    DROP COLUMN IF EXISTS fair_price;

ALTER TABLE live_data.strike_table_hourly
    DROP COLUMN IF EXISTS fair_price;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_ws_15m'
    ) THEN
        EXECUTE 'ALTER TABLE live_data.strike_table_ws_15m DROP COLUMN IF EXISTS fair_price';
    END IF;
END $$;
