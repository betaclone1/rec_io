-- Kalshi 1m candlesticks for default backtest_market_simulator ticker (local / testing).

CREATE TABLE testing."candlesticks_1m_KXBTC15M-26MAR191745-45" (
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_period_ts BIGINT NOT NULL,
    market_ticker TEXT NOT NULL DEFAULT 'KXBTC15M-26MAR191745-45',
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

COMMENT ON TABLE testing."candlesticks_1m_KXBTC15M-26MAR191745-45" IS
    'Kalshi 1-minute candlesticks for backtest_market_simulator default ticker (testing).';

COMMENT ON COLUMN testing."candlesticks_1m_KXBTC15M-26MAR191745-45"."timestamp" IS
    'Bar end instant as US Eastern wall time, no TZ (join with historical_data.btc_price_history.timestamp).';
