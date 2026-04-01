-- Restore objects commonly removed by a mistaken "housekeeping" DROP that targeted hourly and
-- per-symbol tables. Safe to re-run (CREATE IF NOT EXISTS). Also removes a phantom migration
-- row if the old housekeeping migration id was applied from a deleted file.

DELETE FROM system.schema_migrations
WHERE migration_id = '20260327_2100_drop_spx_ndx_eth_symbol_market_strike_housekeeping';

CREATE SCHEMA IF NOT EXISTS historical_data;

-- historical_data: SPX/NDX series (shape matches MASTER_DB_SCHEMA_REFERENCE / prior prod)
CREATE TABLE IF NOT EXISTS historical_data.ndx_price_history (
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    open NUMERIC(20,8),
    high NUMERIC(20,8),
    low NUMERIC(20,8),
    close NUMERIC(20,8),
    volume NUMERIC(20,8),
    momentum NUMERIC(10,4),
    momentum_percentile NUMERIC(5,1),
    volatility NUMERIC(15,6),
    volatility_percentile NUMERIC(5,1),
    movement NUMERIC(10,4),
    movement_percentile NUMERIC(5,1),
    CONSTRAINT ndx_price_history_pkey PRIMARY KEY ("timestamp")
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_ndx_price_history_timestamp
    ON historical_data.ndx_price_history ("timestamp");

CREATE TABLE IF NOT EXISTS historical_data.spx_price_history (
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    open NUMERIC(20,8),
    high NUMERIC(20,8),
    low NUMERIC(20,8),
    close NUMERIC(20,8),
    volume NUMERIC(20,8),
    momentum NUMERIC(10,4),
    momentum_percentile NUMERIC(5,1),
    volatility NUMERIC(15,6),
    volatility_percentile NUMERIC(5,1),
    movement NUMERIC(10,4),
    movement_percentile NUMERIC(5,1),
    CONSTRAINT spx_price_history_pkey PRIMARY KEY ("timestamp")
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_spx_price_history_timestamp
    ON historical_data.spx_price_history ("timestamp");

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

CREATE TABLE IF NOT EXISTS live_data.price_change_spx (
    id SERIAL PRIMARY KEY,
    change1h DECIMAL(10,6),
    change3h DECIMAL(10,6),
    change1d DECIMAL(10,6),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Kalshi market tables (pattern from legacy kalshi_market_watchdog; archived under archive/2026-03-legacy-kalshi-market-watchdog/)
CREATE TABLE IF NOT EXISTS live_data.market_kalshi_hourly_btc (
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

CREATE TABLE IF NOT EXISTS live_data.market_kalshi_hourly_eth (
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
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_hourly_btc_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_hourly_btc
            ADD CONSTRAINT market_kalshi_hourly_btc_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_kalshi_hourly_eth_event_market_unique') THEN
        ALTER TABLE live_data.market_kalshi_hourly_eth
            ADD CONSTRAINT market_kalshi_hourly_eth_event_market_unique UNIQUE (event_ticker, market_ticker);
    END IF;
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

-- Hourly strike tables (match strike_table_hourly_btc in database.py); required before init_database DO alters.
CREATE TABLE IF NOT EXISTS live_data.strike_table_hourly_eth (
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
    yes_ask_min_15m NUMERIC(18,4),
    yes_ask_max_15m NUMERIC(18,4),
    no_ask_min_15m NUMERIC(18,4),
    no_ask_max_15m NUMERIC(18,4),
    yes_ask_range_15m NUMERIC(18,4),
    no_ask_range_15m NUMERIC(18,4),
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
    yes_ask_min_15m NUMERIC(18,4),
    yes_ask_max_15m NUMERIC(18,4),
    no_ask_min_15m NUMERIC(18,4),
    no_ask_max_15m NUMERIC(18,4),
    yes_ask_range_15m NUMERIC(18,4),
    no_ask_range_15m NUMERIC(18,4),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
