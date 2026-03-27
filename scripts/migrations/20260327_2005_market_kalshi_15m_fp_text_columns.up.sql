-- Normalize fixed-point Kalshi fields to API-aligned text columns on unified 15m market table.
-- - volume_fp: TEXT fixed-point (2dp) instead of INTEGER
-- - open_interest_fp: TEXT fixed-point (2dp), replacing legacy open_interest INTEGER

ALTER TABLE live_data.market_kalshi_15m
    ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;

-- Backfill open_interest_fp from legacy integer column when present.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'live_data'
          AND table_name = 'market_kalshi_15m'
          AND column_name = 'open_interest'
    ) THEN
        EXECUTE $sql$
            UPDATE live_data.market_kalshi_15m
            SET open_interest_fp = COALESCE(
                open_interest_fp,
                trim(to_char(open_interest::bigint, 'FM9999999999999999999')) || '.00'
            )
            WHERE open_interest IS NOT NULL
        $sql$;
    END IF;
END $$;

ALTER TABLE live_data.market_kalshi_15m
    ALTER COLUMN volume_fp TYPE TEXT USING (
        CASE
            WHEN volume_fp IS NULL THEN NULL
            ELSE trim(to_char(volume_fp::bigint, 'FM9999999999999999999')) || '.00'
        END
    );

ALTER TABLE live_data.market_kalshi_15m
    DROP COLUMN IF EXISTS open_interest;
