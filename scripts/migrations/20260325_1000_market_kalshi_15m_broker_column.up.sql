-- Add broker (after symbol) to unified 15m market table for multi-vendor reads later.
-- Rebuild table to get column order: id, symbol, broker, event_ticker, ...

CREATE TABLE live_data.market_kalshi_15m_rebuild (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    broker VARCHAR(20) NOT NULL,
    event_ticker VARCHAR(50) NOT NULL,
    market_ticker VARCHAR(100) NOT NULL,
    market TEXT DEFAULT '15m',
    strike VARCHAR(20),
    yes_bid INTEGER,
    yes_ask INTEGER,
    no_bid INTEGER,
    no_ask INTEGER,
    last_price INTEGER,
    yes_bid_dollars TEXT,
    yes_ask_dollars TEXT,
    no_bid_dollars TEXT,
    no_ask_dollars TEXT,
    last_price_dollars TEXT,
    volume_fp INTEGER,
    volume_24h_fp INTEGER,
    open_interest INTEGER,
    liquidity INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT market_kalshi_15m_broker_symbol_event_market_unique
        UNIQUE (broker, symbol, event_ticker, market_ticker)
);

CREATE INDEX market_kalshi_15m_broker_symbol_idx
    ON live_data.market_kalshi_15m_rebuild USING btree (broker, symbol);
CREATE INDEX market_kalshi_15m_broker_symbol_event_idx
    ON live_data.market_kalshi_15m_rebuild USING btree (broker, symbol, event_ticker);

INSERT INTO live_data.market_kalshi_15m_rebuild (
    symbol, broker, event_ticker, market_ticker, market, strike,
    yes_bid, yes_ask, no_bid, no_ask, last_price,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
    volume_fp, volume_24h_fp, open_interest, liquidity, created_at, updated_at
)
SELECT
    symbol,
    'kalshi',
    event_ticker, market_ticker, market, strike,
    yes_bid, yes_ask, no_bid, no_ask, last_price,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
    volume_fp, volume_24h_fp, open_interest, liquidity, created_at, updated_at
FROM live_data.market_kalshi_15m;

DROP TABLE live_data.market_kalshi_15m;

ALTER TABLE live_data.market_kalshi_15m_rebuild RENAME TO market_kalshi_15m;

ALTER SEQUENCE live_data.market_kalshi_15m_rebuild_id_seq RENAME TO market_kalshi_15m_id_seq;

ALTER TABLE live_data.market_kalshi_15m
    RENAME CONSTRAINT market_kalshi_15m_rebuild_pkey TO market_kalshi_15m_pkey;
