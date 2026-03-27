-- Roll back unified 15m fixed-point text columns to legacy integer shape.

ALTER TABLE live_data.market_kalshi_15m
    ADD COLUMN IF NOT EXISTS open_interest INTEGER;

UPDATE live_data.market_kalshi_15m
SET open_interest = CASE
    WHEN open_interest_fp IS NULL OR trim(open_interest_fp) = '' THEN NULL
    ELSE ROUND(open_interest_fp::numeric)::integer
END
WHERE open_interest IS NULL;

ALTER TABLE live_data.market_kalshi_15m
    ALTER COLUMN volume_fp TYPE INTEGER USING (
        CASE
            WHEN volume_fp IS NULL OR trim(volume_fp) = '' THEN NULL
            ELSE ROUND(volume_fp::numeric)::integer
        END
    );

ALTER TABLE live_data.market_kalshi_15m
    DROP COLUMN IF EXISTS open_interest_fp;
