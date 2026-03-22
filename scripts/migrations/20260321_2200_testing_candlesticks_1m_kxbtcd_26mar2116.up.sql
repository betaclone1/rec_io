-- One-hour 1m Kalshi candlestick store (testing). Table name embeds market ticker; identifier is quoted
-- because the ticker contains '-' and '.'.

CREATE TABLE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99" (
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
    api_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT candlesticks_1m_kxbtcd_26mar2116_t70399_99_pkey PRIMARY KEY (end_period_ts)
);

COMMENT ON TABLE testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99" IS
    'Kalshi 1-minute candlesticks for a single market (final hour / backfill experiment). Ticker in table name.';
