-- Drop api_payload; put US-Eastern "timestamp" first (price_history convention). Rebuild to reorder columns.

CREATE TABLE testing.candle_1m_kxbtcd_26mar2116_rebuild (
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_period_ts BIGINT NOT NULL,
    market_ticker TEXT NOT NULL DEFAULT 'KXBTCD-26MAR2116-T70399.99',
    price_open_dollars NUMERIC(20, 6),
    price_high_dollars NUMERIC(20, 6),
    price_low_dollars NUMERIC(20, 6),
    price_close_dollars NUMERIC(20, 6),
    price_mean_dollars NUMERIC(20, 6),
    price_previous_dollars NUMERIC(20, 6),
    yes_bid_open_dollars NUMERIC(20, 6),
    yes_bid_high_dollars NUMERIC(20, 6),
    yes_bid_low_dollars NUMERIC(20, 6),
    yes_bid_close_dollars NUMERIC(20, 6),
    yes_ask_open_dollars NUMERIC(20, 6),
    yes_ask_high_dollars NUMERIC(20, 6),
    yes_ask_low_dollars NUMERIC(20, 6),
    yes_ask_close_dollars NUMERIC(20, 6),
    volume_fp NUMERIC(20, 2),
    open_interest_fp NUMERIC(20, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (end_period_ts)
);

INSERT INTO testing.candle_1m_kxbtcd_26mar2116_rebuild (
    "timestamp",
    end_period_ts,
    market_ticker,
    price_open_dollars,
    price_high_dollars,
    price_low_dollars,
    price_close_dollars,
    price_mean_dollars,
    price_previous_dollars,
    yes_bid_open_dollars,
    yes_bid_high_dollars,
    yes_bid_low_dollars,
    yes_bid_close_dollars,
    yes_ask_open_dollars,
    yes_ask_high_dollars,
    yes_ask_low_dollars,
    yes_ask_close_dollars,
    volume_fp,
    open_interest_fp,
    created_at
)
SELECT
    "timestamp",
    end_period_ts,
    market_ticker,
    price_open_dollars,
    price_high_dollars,
    price_low_dollars,
    price_close_dollars,
    price_mean_dollars,
    price_previous_dollars,
    yes_bid_open_dollars,
    yes_bid_high_dollars,
    yes_bid_low_dollars,
    yes_bid_close_dollars,
    yes_ask_open_dollars,
    yes_ask_high_dollars,
    yes_ask_low_dollars,
    yes_ask_close_dollars,
    volume_fp,
    open_interest_fp,
    created_at
FROM testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99";

DROP TABLE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99";

ALTER TABLE testing.candle_1m_kxbtcd_26mar2116_rebuild
    RENAME TO "candlesticks_1m_KXBTCD-26MAR2116-T70399.99";

COMMENT ON TABLE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99" IS
    'Kalshi 1-minute candlesticks for a single market (final hour / backfill experiment). Ticker in table name.';

COMMENT ON COLUMN testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99"."timestamp" IS
    'Bar end instant as US Eastern wall time, no TZ (same convention as historical_data.btc_price_history.timestamp).';
