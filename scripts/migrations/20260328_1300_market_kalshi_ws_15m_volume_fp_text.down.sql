ALTER TABLE live_data.market_kalshi_ws_15m
    ALTER COLUMN volume_fp TYPE INTEGER USING (
        CASE
            WHEN volume_fp IS NULL OR trim(volume_fp) = '' THEN NULL
            ELSE trim(volume_fp)::numeric::integer
        END
    );
