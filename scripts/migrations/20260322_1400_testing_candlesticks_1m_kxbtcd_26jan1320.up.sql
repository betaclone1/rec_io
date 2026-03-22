-- Kalshi 1m candlesticks for KXBTCD-26JAN1320-T95499.99 (testing). Matches
-- testing."candlesticks_1m_KXBTCD-26MAR2116-T70399.99" shape: "timestamp" first, no api_payload.

CREATE TABLE testing."candlesticks_1m_KXBTCD-26JAN1320-T95499.99" (
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_period_ts BIGINT NOT NULL,
    market_ticker TEXT NOT NULL DEFAULT 'KXBTCD-26JAN1320-T95499.99',
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

COMMENT ON TABLE testing."candlesticks_1m_KXBTCD-26JAN1320-T95499.99" IS
    'Kalshi 1-minute candlesticks for a single market (testing / backfill). Ticker in table name.';

COMMENT ON COLUMN testing."candlesticks_1m_KXBTCD-26JAN1320-T95499.99"."timestamp" IS
    'Bar end instant as US Eastern wall time, no TZ (same convention as historical_data.btc_price_history.timestamp).';
