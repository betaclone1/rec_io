-- Roll back hourly market/strike dollars-fp parity (restore legacy integer quotes + volume_fp int).

-- strike hourly: restore yes_ask/no_ask from dollars
ALTER TABLE live_data.strike_table_hourly_btc
    ADD COLUMN IF NOT EXISTS yes_ask DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_ask DECIMAL(5,2);

UPDATE live_data.strike_table_hourly_btc
SET
    yes_ask = ROUND((yes_ask_dollars::numeric * 100)::numeric, 2),
    no_ask = ROUND((no_ask_dollars::numeric * 100)::numeric, 2)
WHERE yes_ask IS NULL OR no_ask IS NULL;

ALTER TABLE live_data.strike_table_hourly_btc
    ALTER COLUMN volume TYPE INTEGER USING (
        CASE WHEN volume IS NULL THEN NULL ELSE ROUND(volume::numeric)::integer END
    );

ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS open_interest;

ALTER TABLE live_data.strike_table_hourly_eth
    ADD COLUMN IF NOT EXISTS yes_ask DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_ask DECIMAL(5,2);

UPDATE live_data.strike_table_hourly_eth
SET
    yes_ask = ROUND((yes_ask_dollars::numeric * 100)::numeric, 2),
    no_ask = ROUND((no_ask_dollars::numeric * 100)::numeric, 2)
WHERE yes_ask IS NULL OR no_ask IS NULL;

ALTER TABLE live_data.strike_table_hourly_eth
    ALTER COLUMN volume TYPE INTEGER USING (
        CASE WHEN volume IS NULL THEN NULL ELSE ROUND(volume::numeric)::integer END
    );

ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS open_interest;

-- market hourly: restore integer columns (nullable)
ALTER TABLE live_data.market_kalshi_hourly_btc
    ADD COLUMN IF NOT EXISTS yes_bid INTEGER,
    ADD COLUMN IF NOT EXISTS yes_ask INTEGER,
    ADD COLUMN IF NOT EXISTS no_bid INTEGER,
    ADD COLUMN IF NOT EXISTS no_ask INTEGER,
    ADD COLUMN IF NOT EXISTS last_price INTEGER,
    ADD COLUMN IF NOT EXISTS volume_24h_fp INTEGER,
    ADD COLUMN IF NOT EXISTS liquidity INTEGER,
    ADD COLUMN IF NOT EXISTS open_interest INTEGER;

UPDATE live_data.market_kalshi_hourly_btc
SET open_interest = CASE
    WHEN open_interest_fp IS NULL OR trim(open_interest_fp) = '' THEN NULL
    ELSE ROUND(open_interest_fp::numeric)::integer
END
WHERE open_interest IS NULL;

ALTER TABLE live_data.market_kalshi_hourly_btc
    ALTER COLUMN volume_fp TYPE INTEGER USING (
        CASE
            WHEN volume_fp IS NULL OR trim(volume_fp::text) = '' THEN NULL
            ELSE ROUND(volume_fp::numeric)::integer
        END
    );

ALTER TABLE live_data.market_kalshi_hourly_btc DROP COLUMN IF EXISTS open_interest_fp;

ALTER TABLE live_data.market_kalshi_hourly_eth
    ADD COLUMN IF NOT EXISTS yes_bid INTEGER,
    ADD COLUMN IF NOT EXISTS yes_ask INTEGER,
    ADD COLUMN IF NOT EXISTS no_bid INTEGER,
    ADD COLUMN IF NOT EXISTS no_ask INTEGER,
    ADD COLUMN IF NOT EXISTS last_price INTEGER,
    ADD COLUMN IF NOT EXISTS volume_24h_fp INTEGER,
    ADD COLUMN IF NOT EXISTS liquidity INTEGER,
    ADD COLUMN IF NOT EXISTS open_interest INTEGER;

UPDATE live_data.market_kalshi_hourly_eth
SET open_interest = CASE
    WHEN open_interest_fp IS NULL OR trim(open_interest_fp) = '' THEN NULL
    ELSE ROUND(open_interest_fp::numeric)::integer
END
WHERE open_interest IS NULL;

ALTER TABLE live_data.market_kalshi_hourly_eth
    ALTER COLUMN volume_fp TYPE INTEGER USING (
        CASE
            WHEN volume_fp IS NULL OR trim(volume_fp::text) = '' THEN NULL
            ELSE ROUND(volume_fp::numeric)::integer
        END
    );

ALTER TABLE live_data.market_kalshi_hourly_eth DROP COLUMN IF EXISTS open_interest_fp;
