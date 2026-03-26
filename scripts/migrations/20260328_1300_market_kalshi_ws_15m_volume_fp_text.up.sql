-- volume_fp: store Kalshi fixed-point string with 2 fractional digits (matches API volume_fp), not INTEGER.

ALTER TABLE live_data.market_kalshi_ws_15m
    ALTER COLUMN volume_fp TYPE TEXT USING (
        CASE
            WHEN volume_fp IS NULL THEN NULL
            ELSE trim(to_char(volume_fp::bigint, 'FM9999999999999999999')) || '.00'
        END
    );
