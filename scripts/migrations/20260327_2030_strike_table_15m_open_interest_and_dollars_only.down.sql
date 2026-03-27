-- Roll back strike_table_15m to legacy ask-cents columns and integer volume.

ALTER TABLE live_data.strike_table_15m
    ADD COLUMN IF NOT EXISTS yes_ask DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_ask DECIMAL(5,2);

UPDATE live_data.strike_table_15m
SET
    yes_ask = ROUND((yes_ask_dollars::numeric * 100)::numeric, 2),
    no_ask = ROUND((no_ask_dollars::numeric * 100)::numeric, 2)
WHERE yes_ask IS NULL OR no_ask IS NULL;

ALTER TABLE live_data.strike_table_15m
    ALTER COLUMN volume TYPE INTEGER USING (
        CASE
            WHEN volume IS NULL THEN NULL
            ELSE ROUND(volume::numeric)::integer
        END
    );

ALTER TABLE live_data.strike_table_15m
    DROP COLUMN IF EXISTS open_interest;
