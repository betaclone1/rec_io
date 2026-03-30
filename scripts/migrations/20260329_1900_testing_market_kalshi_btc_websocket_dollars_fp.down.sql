-- Restore prior integer-cent testing table (empty shape; data from pre-up is not recovered).

DROP TABLE IF EXISTS testing.market_kalshi_btc_websocket CASCADE;

CREATE TABLE testing.market_kalshi_btc_websocket (
    id SERIAL PRIMARY KEY,
    event_ticker VARCHAR(50) NOT NULL,
    market_ticker VARCHAR(100) NOT NULL,
    market TEXT,
    strike VARCHAR(20),
    yes_bid INTEGER,
    yes_ask INTEGER,
    no_bid INTEGER,
    no_ask INTEGER,
    last_price INTEGER,
    volume INTEGER,
    volume_24h INTEGER,
    open_interest INTEGER,
    liquidity INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    yes_volume INTEGER,
    no_volume INTEGER,
    CONSTRAINT market_kalshi_btc_websocket_event_ticker_market_ticker_key UNIQUE (event_ticker, market_ticker)
);
