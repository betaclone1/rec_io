-- Unified Kalshi 15m market snapshot for all tracked symbols (one row per market/strike per symbol).
-- Written by backend/market_watchdog.py; legacy per-symbol tables remain for cutover.

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_15m (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
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
    CONSTRAINT market_kalshi_15m_symbol_event_market_unique UNIQUE (symbol, event_ticker, market_ticker)
);

CREATE INDEX IF NOT EXISTS market_kalshi_15m_symbol_idx
    ON live_data.market_kalshi_15m USING btree (symbol);

CREATE INDEX IF NOT EXISTS market_kalshi_15m_symbol_event_idx
    ON live_data.market_kalshi_15m USING btree (symbol, event_ticker);
