-- Durable backtest working table: Kalshi 1m candles + settlement metadata (floor_strike, market_result).

CREATE SCHEMA IF NOT EXISTS backtest;

CREATE TABLE backtest.kalshi_candles_1m_kxbtc15m_26mar051345_45 (
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    end_period_ts BIGINT NOT NULL,
    market_ticker TEXT NOT NULL DEFAULT 'KXBTC15M-26MAR051345-45',
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
    floor_strike NUMERIC(24, 8),
    market_result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (end_period_ts)
);

COMMENT ON SCHEMA backtest IS
    'Working tables for offline backtests (ingested Kalshi + joins to historical_data).';

COMMENT ON TABLE backtest.kalshi_candles_1m_kxbtc15m_26mar051345_45 IS
    'Kalshi 1m candlesticks for KXBTC15M-26MAR051345-45 with floor_strike and market_result from '
    'GET /historical/markets (when present) or GET /markets (fallback). Populate: '
    'scripts/backtest/ingest_kalshi_backtest_market.py.';

COMMENT ON COLUMN backtest.kalshi_candles_1m_kxbtc15m_26mar051345_45."timestamp" IS
    'Bar end instant as US Eastern wall time, no TZ (same as testing Kalshi candle tables).';

COMMENT ON COLUMN backtest.kalshi_candles_1m_kxbtc15m_26mar051345_45.market_result IS
    'Kalshi market ``result`` (e.g. yes, no); repeated on each candle row for convenience.';
