-- Restore NUMERIC volume / open_interest on strike tables (rollback fp TEXT columns).

ALTER TABLE live_data.strike_table_15m ADD COLUMN IF NOT EXISTS volume NUMERIC(20,2);
ALTER TABLE live_data.strike_table_15m ADD COLUMN IF NOT EXISTS open_interest NUMERIC(20,2);

UPDATE live_data.strike_table_15m
SET volume = CASE
    WHEN volume_fp IS NULL OR trim(volume_fp) = '' THEN NULL
    ELSE round(volume_fp::numeric, 2)
END
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m' AND column_name = 'volume_fp'
);

UPDATE live_data.strike_table_15m
SET open_interest = CASE
    WHEN open_interest_fp IS NULL OR trim(open_interest_fp) = '' THEN NULL
    ELSE round(open_interest_fp::numeric, 2)
END
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_15m' AND column_name = 'open_interest_fp'
);

ALTER TABLE live_data.strike_table_15m DROP COLUMN IF EXISTS volume_fp;
ALTER TABLE live_data.strike_table_15m DROP COLUMN IF EXISTS open_interest_fp;

ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS volume NUMERIC(20,2);
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS open_interest NUMERIC(20,2);

UPDATE live_data.strike_table_hourly_btc
SET volume = CASE
    WHEN volume_fp IS NULL OR trim(volume_fp) = '' THEN NULL
    ELSE round(volume_fp::numeric, 2)
END
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc' AND column_name = 'volume_fp'
);

UPDATE live_data.strike_table_hourly_btc
SET open_interest = CASE
    WHEN open_interest_fp IS NULL OR trim(open_interest_fp) = '' THEN NULL
    ELSE round(open_interest_fp::numeric, 2)
END
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc' AND column_name = 'open_interest_fp'
);

ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS volume_fp;
ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS open_interest_fp;

ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS volume NUMERIC(20,2);
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS open_interest NUMERIC(20,2);

UPDATE live_data.strike_table_hourly_eth
SET volume = CASE
    WHEN volume_fp IS NULL OR trim(volume_fp) = '' THEN NULL
    ELSE round(volume_fp::numeric, 2)
END
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth' AND column_name = 'volume_fp'
);

UPDATE live_data.strike_table_hourly_eth
SET open_interest = CASE
    WHEN open_interest_fp IS NULL OR trim(open_interest_fp) = '' THEN NULL
    ELSE round(open_interest_fp::numeric, 2)
END
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth' AND column_name = 'open_interest_fp'
);

ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS volume_fp;
ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS open_interest_fp;
