-- Align testing websocket sink with production Kalshi market rows: dollar TEXT quotes + volume_fp/open_interest_fp only.

DROP TABLE IF EXISTS testing.market_kalshi_btc_websocket CASCADE;

CREATE TABLE testing.market_kalshi_btc_websocket (
    id SERIAL PRIMARY KEY,
    event_ticker VARCHAR(50) NOT NULL,
    market_ticker VARCHAR(100) NOT NULL,
    market TEXT DEFAULT 'hourly',
    strike VARCHAR(20),
    yes_bid_dollars TEXT,
    yes_ask_dollars TEXT,
    no_bid_dollars TEXT,
    no_ask_dollars TEXT,
    last_price_dollars TEXT,
    volume_fp TEXT,
    open_interest_fp TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT market_kalshi_btc_websocket_event_ticker_market_ticker_key UNIQUE (event_ticker, market_ticker)
);
