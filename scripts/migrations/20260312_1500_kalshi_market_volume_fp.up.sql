DO $$
DECLARE
    tbl text;
BEGIN
    -- Hourly market tables
    FOREACH tbl IN ARRAY ARRAY[
        'market_kalshi_hourly_btc',
        'market_kalshi_hourly_eth',
        'market_kalshi_hourly_ndx',
        'market_kalshi_hourly_spx'
    ] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'live_data'
              AND table_name = tbl
              AND column_name = 'volume'
        ) THEN
            EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN volume TO volume_fp;', tbl);
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'live_data'
              AND table_name = tbl
              AND column_name = 'volume_24h'
        ) THEN
            EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN volume_24h TO volume_24h_fp;', tbl);
        END IF;
    END LOOP;

    -- 15m market tables (BTC/ETH)
    FOREACH tbl IN ARRAY ARRAY[
        'market_kalshi_15m_btc',
        'market_kalshi_15m_eth'
    ] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'live_data'
              AND table_name = tbl
              AND column_name = 'volume'
        ) THEN
            EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN volume TO volume_fp;', tbl);
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'live_data'
              AND table_name = tbl
              AND column_name = 'volume_24h'
        ) THEN
            EXECUTE format('ALTER TABLE live_data.%I RENAME COLUMN volume_24h TO volume_24h_fp;', tbl);
        END IF;
    END LOOP;
END
$$;

