-- strike_table_15m: preserve dollar-price columns as source of truth, remove legacy cents ask columns.
-- Also preserve fixed-point market depth precision by widening volume and adding open_interest.

ALTER TABLE live_data.strike_table_15m
    ADD COLUMN IF NOT EXISTS open_interest NUMERIC(20,2);

ALTER TABLE live_data.strike_table_15m
    ALTER COLUMN volume TYPE NUMERIC(20,2) USING (
        CASE
            WHEN volume IS NULL THEN NULL
            ELSE ROUND(volume::numeric, 2)
        END
    );

ALTER TABLE live_data.strike_table_15m
    DROP COLUMN IF EXISTS yes_ask,
    DROP COLUMN IF EXISTS no_ask;
