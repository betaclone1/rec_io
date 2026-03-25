-- Unified 15m strike table: all symbols, broker + symbol (venue/source). exchange_display removed in 20260325_1600.
-- Populated by strike_table_generator.py --master-15m. Per-symbol strike_table_15m_* remain until cutover.

CREATE TABLE IF NOT EXISTS live_data.strike_table_15m (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    broker VARCHAR(20) NOT NULL,
    market TEXT DEFAULT '15m',
    current_price NUMERIC(18,5),
    ttc_hourly INTEGER,
    ttc_15m INTEGER,
    exchange_display VARCHAR(32) NOT NULL DEFAULT 'Kalshi',
    event_ticker VARCHAR(50),
    market_title TEXT,
    strike_tier INTEGER,
    market_status VARCHAR(20),
    strike NUMERIC(18,5),
    buffer NUMERIC(18,5),
    buffer_pct NUMERIC(12,6),
    probability_hourly DECIMAL(5,2),
    probability_15m DECIMAL(5,2),
    yes_ask DECIMAL(5,2),
    no_ask DECIMAL(5,2),
    yes_ask_dollars TEXT,
    no_ask_dollars TEXT,
    yes_bid_dollars TEXT,
    no_bid_dollars TEXT,
    yes_price_spread NUMERIC(6,4),
    no_price_spread NUMERIC(6,4),
    yes_diff DECIMAL(5,2),
    no_diff DECIMAL(5,2),
    volume INTEGER,
    ticker VARCHAR(50),
    active_side VARCHAR(10),
    momentum_weighted_score DECIMAL(5,3),
    momentum_percentile DECIMAL(5,1),
    volatility NUMERIC(10,6),
    volatility_percentile NUMERIC(5,1),
    movement NUMERIC(10,4),
    movement_percentile NUMERIC(5,1),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS strike_table_15m_broker_symbol_idx
    ON live_data.strike_table_15m USING btree (broker, symbol);

CREATE INDEX IF NOT EXISTS idx_strike_table_15m_lookup
    ON live_data.strike_table_15m USING btree (timestamp, symbol, current_price);

CREATE INDEX IF NOT EXISTS strike_table_15m_broker_symbol_timestamp_idx
    ON live_data.strike_table_15m USING btree (broker, symbol, timestamp DESC);
