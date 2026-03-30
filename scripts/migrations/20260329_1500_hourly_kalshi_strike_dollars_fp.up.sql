-- Hourly Kalshi market + strike: align with unified 15m (_dollars + volume_fp/open_interest_fp TEXT on market;
-- strike: yes_ask_dollars only, numeric volume + open_interest).

-- --- market_kalshi_hourly_btc ---
ALTER TABLE live_data.market_kalshi_hourly_btc ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;

DO $bc$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'market_kalshi_hourly_btc' AND column_name = 'open_interest'
  ) THEN
    UPDATE live_data.market_kalshi_hourly_btc
    SET open_interest_fp = COALESCE(
        open_interest_fp,
        CASE
            WHEN open_interest IS NULL THEN NULL
            ELSE trim(to_char(open_interest::bigint, 'FM9999999999999999999')) || '.00'
        END
    )
    WHERE open_interest IS NOT NULL;
  END IF;
END $bc$;

ALTER TABLE live_data.market_kalshi_hourly_btc
    ALTER COLUMN volume_fp TYPE TEXT USING (
        CASE
            WHEN volume_fp IS NULL THEN NULL
            ELSE trim(to_char(volume_fp::bigint, 'FM9999999999999999999')) || '.00'
        END
    );

ALTER TABLE live_data.market_kalshi_hourly_btc
    DROP COLUMN IF EXISTS yes_bid,
    DROP COLUMN IF EXISTS yes_ask,
    DROP COLUMN IF EXISTS no_bid,
    DROP COLUMN IF EXISTS no_ask,
    DROP COLUMN IF EXISTS last_price,
    DROP COLUMN IF EXISTS volume_24h_fp,
    DROP COLUMN IF EXISTS liquidity,
    DROP COLUMN IF EXISTS open_interest;

-- --- market_kalshi_hourly_eth ---
ALTER TABLE live_data.market_kalshi_hourly_eth ADD COLUMN IF NOT EXISTS open_interest_fp TEXT;

DO $et$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'market_kalshi_hourly_eth' AND column_name = 'open_interest'
  ) THEN
    UPDATE live_data.market_kalshi_hourly_eth
    SET open_interest_fp = COALESCE(
        open_interest_fp,
        CASE
            WHEN open_interest IS NULL THEN NULL
            ELSE trim(to_char(open_interest::bigint, 'FM9999999999999999999')) || '.00'
        END
    )
    WHERE open_interest IS NOT NULL;
  END IF;
END $et$;

ALTER TABLE live_data.market_kalshi_hourly_eth
    ALTER COLUMN volume_fp TYPE TEXT USING (
        CASE
            WHEN volume_fp IS NULL THEN NULL
            ELSE trim(to_char(volume_fp::bigint, 'FM9999999999999999999')) || '.00'
        END
    );

ALTER TABLE live_data.market_kalshi_hourly_eth
    DROP COLUMN IF EXISTS yes_bid,
    DROP COLUMN IF EXISTS yes_ask,
    DROP COLUMN IF EXISTS no_bid,
    DROP COLUMN IF EXISTS no_ask,
    DROP COLUMN IF EXISTS last_price,
    DROP COLUMN IF EXISTS volume_24h_fp,
    DROP COLUMN IF EXISTS liquidity,
    DROP COLUMN IF EXISTS open_interest;

-- --- strike_table_hourly_btc ---
-- Ensure dollar ask columns exist before dropping legacy cent asks (avoids empty INSERT target).
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS yes_ask_dollars TEXT;
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS no_ask_dollars TEXT;

ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS open_interest NUMERIC(20,2);

ALTER TABLE live_data.strike_table_hourly_btc
    ALTER COLUMN volume TYPE NUMERIC(20,2) USING (
        CASE
            WHEN volume IS NULL THEN NULL
            ELSE ROUND(volume::numeric, 2)
        END
    );

ALTER TABLE live_data.strike_table_hourly_btc
    DROP COLUMN IF EXISTS yes_ask,
    DROP COLUMN IF EXISTS no_ask;

-- --- strike_table_hourly_eth ---
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS yes_ask_dollars TEXT;
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS no_ask_dollars TEXT;

ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS open_interest NUMERIC(20,2);

ALTER TABLE live_data.strike_table_hourly_eth
    ALTER COLUMN volume TYPE NUMERIC(20,2) USING (
        CASE
            WHEN volume IS NULL THEN NULL
            ELSE ROUND(volume::numeric, 2)
        END
    );

ALTER TABLE live_data.strike_table_hourly_eth
    DROP COLUMN IF EXISTS yes_ask,
    DROP COLUMN IF EXISTS no_ask;
