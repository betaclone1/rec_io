-- Roll back 20260331_1200_live_data_drop_legacy_split_and_equity_tables.
-- Recreates empty tables/indexes (no row restore). Re-run later migrations for full column parity if needed.

CREATE TABLE IF NOT EXISTS live_data.eth_price_log (
    id SERIAL PRIMARY KEY,
    price DECIMAL(15,2),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_spx (
    timestamp TEXT PRIMARY KEY,
    price DECIMAL(10,2),
    one_minute_avg DECIMAL(10,2),
    momentum DECIMAL(10,4),
    delta_1m DECIMAL(10,4),
    delta_2m DECIMAL(10,4),
    delta_3m DECIMAL(10,4),
    delta_4m DECIMAL(10,4),
    delta_15m DECIMAL(10,4),
    delta_30m DECIMAL(10,4),
    move_1m DECIMAL(10,4),
    move_2m DECIMAL(10,4),
    move_3m DECIMAL(10,4),
    move_4m DECIMAL(10,4),
    move_15m DECIMAL(10,4),
    move_30m DECIMAL(10,4),
    movement DECIMAL(10,4),
    movement_percentile DECIMAL(5,1)
);

CREATE INDEX IF NOT EXISTS idx_live_price_log_1s_spx_timestamp
    ON live_data.live_price_log_1s_spx USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_ndx (
    timestamp TEXT PRIMARY KEY,
    price DECIMAL(10,2),
    one_minute_avg DECIMAL(10,2),
    momentum DECIMAL(10,4),
    delta_1m DECIMAL(10,4),
    delta_2m DECIMAL(10,4),
    delta_3m DECIMAL(10,4),
    delta_4m DECIMAL(10,4),
    delta_15m DECIMAL(10,4),
    delta_30m DECIMAL(10,4),
    move_1m DECIMAL(10,4),
    move_2m DECIMAL(10,4),
    move_3m DECIMAL(10,4),
    move_4m DECIMAL(10,4),
    move_15m DECIMAL(10,4),
    move_30m DECIMAL(10,4),
    movement DECIMAL(10,4),
    movement_percentile DECIMAL(5,1)
);

CREATE INDEX IF NOT EXISTS live_price_log_1s_ndx_timestamp_idx
    ON live_data.live_price_log_1s_ndx USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.price_change_spx (
    id SERIAL PRIMARY KEY,
    change1h DECIMAL(10,6),
    change3h DECIMAL(10,6),
    change1d DECIMAL(10,6),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_hourly_ndx (
    id SERIAL PRIMARY KEY,
    event_ticker VARCHAR(50) NOT NULL,
    market_ticker VARCHAR(100) NOT NULL,
    market TEXT DEFAULT 'hourly',
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_hourly_spx (
    id SERIAL PRIMARY KEY,
    event_ticker VARCHAR(50) NOT NULL,
    market_ticker VARCHAR(100) NOT NULL,
    market TEXT DEFAULT 'hourly',
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_hourly_ndx_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_hourly_ndx
            ADD CONSTRAINT market_kalshi_hourly_ndx_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_hourly_spx_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_hourly_spx
            ADD CONSTRAINT market_kalshi_hourly_spx_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_15m_btc (
    id SERIAL PRIMARY KEY,
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_15m_eth (
    id SERIAL PRIMARY KEY,
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_15m_sol (
    id SERIAL PRIMARY KEY,
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_15m_xrp (
    id SERIAL PRIMARY KEY,
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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_15m_btc_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_15m_btc
            ADD CONSTRAINT market_kalshi_15m_btc_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_15m_eth_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_15m_eth
            ADD CONSTRAINT market_kalshi_15m_eth_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_15m_sol_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_15m_sol
            ADD CONSTRAINT market_kalshi_15m_sol_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_15m_xrp_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_15m_xrp
            ADD CONSTRAINT market_kalshi_15m_xrp_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
END $$;

-- Hourly equity strike tables (shape matches strike_table_hourly_btc after prior migrations).
CREATE TABLE IF NOT EXISTS live_data.strike_table_hourly_ndx (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
    symbol VARCHAR(10),
    market TEXT DEFAULT 'hourly',
    current_price DECIMAL(10,2),
    ttc_hourly INTEGER,
    broker VARCHAR(20),
    event_ticker VARCHAR(50),
    market_title TEXT,
    strike_tier INTEGER,
    market_status VARCHAR(20),
    strike INTEGER,
    buffer DECIMAL(10,2),
    buffer_pct DECIMAL(5,2),
    probability_hourly DECIMAL(5,2),
    yes_ask DECIMAL(5,2),
    no_ask DECIMAL(5,2),
    yes_diff DECIMAL(5,2),
    no_diff DECIMAL(5,2),
    volume INTEGER,
    ticker VARCHAR(50),
    active_side VARCHAR(10),
    momentum_weighted_score DECIMAL(5,3),
    yes_ask_min_15m NUMERIC(18,4),
    yes_ask_max_15m NUMERIC(18,4),
    no_ask_min_15m NUMERIC(18,4),
    no_ask_max_15m NUMERIC(18,4),
    yes_ask_range_15m NUMERIC(18,4),
    no_ask_range_15m NUMERIC(18,4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_data.strike_table_hourly_spx (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
    symbol VARCHAR(10),
    market TEXT DEFAULT 'hourly',
    current_price DECIMAL(10,2),
    ttc_hourly INTEGER,
    broker VARCHAR(20),
    event_ticker VARCHAR(50),
    market_title TEXT,
    strike_tier INTEGER,
    market_status VARCHAR(20),
    strike INTEGER,
    buffer DECIMAL(10,2),
    buffer_pct DECIMAL(5,2),
    probability_hourly DECIMAL(5,2),
    yes_ask DECIMAL(5,2),
    no_ask DECIMAL(5,2),
    yes_diff DECIMAL(5,2),
    no_diff DECIMAL(5,2),
    volume INTEGER,
    ticker VARCHAR(50),
    active_side VARCHAR(10),
    momentum_weighted_score DECIMAL(5,3),
    yes_ask_min_15m NUMERIC(18,4),
    yes_ask_max_15m NUMERIC(18,4),
    no_ask_min_15m NUMERIC(18,4),
    no_ask_max_15m NUMERIC(18,4),
    yes_ask_range_15m NUMERIC(18,4),
    no_ask_range_15m NUMERIC(18,4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Per-symbol 15m strike tables (legacy split; unified table is strike_table_15m).
CREATE TABLE IF NOT EXISTS live_data.strike_table_15m_btc (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
    symbol VARCHAR(10),
    market TEXT DEFAULT '15m',
    current_price NUMERIC(18,5),
    ttc_hourly INTEGER,
    probability_hourly DECIMAL(5,2),
    ttc_15m INTEGER,
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
    buffer NUMERIC(18,5),
    buffer_pct NUMERIC(12,6),
    strike NUMERIC(18,5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_data.strike_table_15m_eth (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
    symbol VARCHAR(10),
    market TEXT DEFAULT '15m',
    current_price NUMERIC(18,5),
    ttc_hourly INTEGER,
    probability_hourly DECIMAL(5,2),
    ttc_15m INTEGER,
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
    buffer NUMERIC(18,5),
    buffer_pct NUMERIC(12,6),
    strike NUMERIC(18,5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_data.strike_table_15m_sol (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
    symbol VARCHAR(10),
    market TEXT DEFAULT '15m',
    current_price NUMERIC(18,5),
    ttc_hourly INTEGER,
    probability_hourly DECIMAL(5,2),
    ttc_15m INTEGER,
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
    buffer NUMERIC(18,5),
    buffer_pct NUMERIC(12,6),
    strike NUMERIC(18,5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_data.strike_table_15m_xrp (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
    symbol VARCHAR(10),
    market TEXT DEFAULT '15m',
    current_price NUMERIC(18,5),
    ttc_hourly INTEGER,
    probability_hourly DECIMAL(5,2),
    ttc_15m INTEGER,
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
    buffer NUMERIC(18,5),
    buffer_pct NUMERIC(12,6),
    strike NUMERIC(18,5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_data.strike_table_ws_15m (
    id SERIAL PRIMARY KEY,
    "timestamp" TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    market TEXT DEFAULT '15m',
    current_price NUMERIC(18,5),
    ttc_hourly INTEGER,
    ttc_15m INTEGER,
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

ALTER TABLE live_data.strike_table_ws_15m
    ADD COLUMN IF NOT EXISTS pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pipeline_health_reason TEXT,
    ADD COLUMN IF NOT EXISTS pipeline_health_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 30;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'strike_table_15m_btc',
        'strike_table_15m_eth',
        'strike_table_15m_sol',
        'strike_table_15m_xrp',
        'strike_table_ws_15m'
    ]
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'live_data' AND table_name = t
        ) THEN
            EXECUTE format(
                'ALTER TABLE live_data.%I
                   ADD COLUMN IF NOT EXISTS yes_ask_min_15m NUMERIC(18,4),
                   ADD COLUMN IF NOT EXISTS yes_ask_max_15m NUMERIC(18,4),
                   ADD COLUMN IF NOT EXISTS no_ask_min_15m NUMERIC(18,4),
                   ADD COLUMN IF NOT EXISTS no_ask_max_15m NUMERIC(18,4),
                   ADD COLUMN IF NOT EXISTS yes_ask_range_15m NUMERIC(18,4),
                   ADD COLUMN IF NOT EXISTS no_ask_range_15m NUMERIC(18,4);',
                t
            );
        END IF;
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS strike_table_ws_15m_exchange_symbol_idx
    ON live_data.strike_table_ws_15m USING btree (exchange, symbol);

CREATE INDEX IF NOT EXISTS idx_strike_table_ws_15m_lookup
    ON live_data.strike_table_ws_15m USING btree ("timestamp", symbol, current_price);

CREATE INDEX IF NOT EXISTS strike_table_ws_15m_exchange_symbol_timestamp_idx
    ON live_data.strike_table_ws_15m USING btree (exchange, symbol, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS strike_table_ws_15m_exchange_symbol_health_checked_idx
    ON live_data.strike_table_ws_15m USING btree (exchange, symbol, pipeline_health_checked_at DESC);
