-- Unified hourly Kalshi market + strike tables (BTC+ETH in one table each).
-- Canonical pipeline health: (exchange, market, symbol) + ws_transport_ok_at for WS liveness.
-- Migrates strike_pipeline_health_15m -> strike_pipeline_health with market='15m'.

-- ========== market_kalshi_hourly (unified) ==========
CREATE TABLE IF NOT EXISTS live_data.market_kalshi_hourly (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    event_ticker VARCHAR(50) NOT NULL,
    market_ticker VARCHAR(100) NOT NULL,
    market TEXT DEFAULT 'hourly',
    strike VARCHAR(20),
    volume_fp TEXT,
    open_interest_fp TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    yes_bid_dollars TEXT,
    yes_ask_dollars TEXT,
    no_bid_dollars TEXT,
    no_ask_dollars TEXT,
    last_price_dollars TEXT,
    CONSTRAINT market_kalshi_hourly_ex_sym_evt_mkt_uniq UNIQUE (exchange, symbol, event_ticker, market_ticker)
);

CREATE INDEX IF NOT EXISTS market_kalshi_hourly_exchange_symbol_idx
    ON live_data.market_kalshi_hourly (exchange, symbol);
CREATE INDEX IF NOT EXISTS market_kalshi_hourly_exchange_symbol_event_idx
    ON live_data.market_kalshi_hourly (exchange, symbol, event_ticker);

-- Legacy `market_kalshi_hourly_{btc,eth}` rows often have no symbol/exchange columns (implicit BTC/ETH + kalshi).
INSERT INTO live_data.market_kalshi_hourly (
    symbol, exchange, event_ticker, market_ticker, market, strike,
    volume_fp, open_interest_fp, created_at, updated_at,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars
)
SELECT
    'BTC'::varchar(10),
    'kalshi'::varchar(20),
    event_ticker, market_ticker, COALESCE(market, 'hourly'), strike,
    volume_fp, open_interest_fp, created_at, updated_at,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars
FROM live_data.market_kalshi_hourly_btc
ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO NOTHING;

INSERT INTO live_data.market_kalshi_hourly (
    symbol, exchange, event_ticker, market_ticker, market, strike,
    volume_fp, open_interest_fp, created_at, updated_at,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars
)
SELECT
    'ETH'::varchar(10),
    'kalshi'::varchar(20),
    event_ticker, market_ticker, COALESCE(market, 'hourly'), strike,
    volume_fp, open_interest_fp, created_at, updated_at,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars
FROM live_data.market_kalshi_hourly_eth
ON CONFLICT (exchange, symbol, event_ticker, market_ticker) DO NOTHING;

SELECT setval(
    pg_get_serial_sequence('live_data.market_kalshi_hourly', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data.market_kalshi_hourly), 1)
);

DROP TABLE IF EXISTS live_data.market_kalshi_hourly_btc CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_hourly_eth CASCADE;

-- ========== strike_table_hourly (unified) ==========
-- Rename BTC table first so LIKE ... INCLUDING CONSTRAINTS does not collide on constraint names.
ALTER TABLE live_data.strike_table_hourly_btc RENAME TO strike_table_hourly_btc_old;

CREATE TABLE live_data.strike_table_hourly (
    LIKE live_data.strike_table_hourly_btc_old
    INCLUDING DEFAULTS
    INCLUDING CONSTRAINTS
    INCLUDING IDENTITY
);

-- Prod legacy used `broker`; unified code expects `exchange` (same as 15m).
DO $st_rename$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly'
          AND column_name = 'broker'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly'
          AND column_name = 'exchange'
    ) THEN
        ALTER TABLE live_data.strike_table_hourly RENAME COLUMN broker TO exchange;
    END IF;
END $st_rename$;

-- Same for rename sources before copying rows.
DO $btc_old_norm$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc_old'
          AND column_name = 'broker'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc_old'
          AND column_name = 'exchange'
    ) THEN
        ALTER TABLE live_data.strike_table_hourly_btc_old RENAME COLUMN broker TO exchange;
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc_old'
          AND column_name = 'broker'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc_old'
          AND column_name = 'exchange'
    ) THEN
        UPDATE live_data.strike_table_hourly_btc_old
        SET exchange = COALESCE(
            NULLIF(TRIM(exchange::text), ''),
            NULLIF(TRIM(broker::text), ''),
            'kalshi'
        )
        WHERE exchange IS NULL OR TRIM(COALESCE(exchange::text, '')) = '';
    END IF;
END $btc_old_norm$;

-- Named columns: legacy BTC/ETH tables may differ in physical column order; avoid SELECT *.
INSERT INTO live_data.strike_table_hourly (
    id, "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
    event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
    probability_hourly, probability_15m, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp,
    ticker, active_side, momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
    movement, movement_percentile, yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
    yes_ask_range_15m, no_ask_range_15m, created_at
)
SELECT
    id, "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
    event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
    probability_hourly, probability_15m, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp,
    ticker, active_side, momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
    movement, movement_percentile, yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
    yes_ask_range_15m, no_ask_range_15m, created_at
FROM live_data.strike_table_hourly_btc_old;

DO $eth_norm$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth'
          AND column_name = 'broker'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth'
          AND column_name = 'exchange'
    ) THEN
        ALTER TABLE live_data.strike_table_hourly_eth RENAME COLUMN broker TO exchange;
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth'
          AND column_name = 'broker'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth'
          AND column_name = 'exchange'
    ) THEN
        UPDATE live_data.strike_table_hourly_eth
        SET exchange = COALESCE(
            NULLIF(TRIM(exchange::text), ''),
            NULLIF(TRIM(broker::text), ''),
            'kalshi'
        )
        WHERE exchange IS NULL OR TRIM(COALESCE(exchange::text, '')) = '';
    END IF;
END $eth_norm$;

INSERT INTO live_data.strike_table_hourly (
    id, "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
    event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
    probability_hourly, probability_15m, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp,
    ticker, active_side, momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
    movement, movement_percentile, yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
    yes_ask_range_15m, no_ask_range_15m, created_at
)
SELECT
    id, "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
    event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
    probability_hourly, probability_15m, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp,
    ticker, active_side, momentum_weighted_score, momentum_percentile, volatility, volatility_percentile,
    movement, movement_percentile, yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
    yes_ask_range_15m, no_ask_range_15m, created_at
FROM live_data.strike_table_hourly_eth;

SELECT setval(
    pg_get_serial_sequence('live_data.strike_table_hourly', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data.strike_table_hourly), 1)
);

DROP TABLE IF EXISTS live_data.strike_table_hourly_eth CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_hourly_btc_old CASCADE;

CREATE INDEX IF NOT EXISTS idx_strike_table_hourly_lookup
    ON live_data.strike_table_hourly ("timestamp", symbol, current_price);
CREATE INDEX IF NOT EXISTS strike_table_hourly_exchange_symbol_idx
    ON live_data.strike_table_hourly (exchange, symbol);
CREATE INDEX IF NOT EXISTS strike_table_hourly_exchange_symbol_timestamp_idx
    ON live_data.strike_table_hourly (exchange, symbol, "timestamp" DESC);

-- ========== strike_pipeline_health (replaces strike_pipeline_health_15m) ==========
CREATE TABLE IF NOT EXISTS live_data.strike_pipeline_health (
    exchange VARCHAR(20) NOT NULL,
    market VARCHAR(20) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
    pipeline_health_reason TEXT,
    pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 900,
    ws_transport_ok_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, market, symbol)
);

CREATE INDEX IF NOT EXISTS strike_pipeline_health_checked_idx
    ON live_data.strike_pipeline_health (pipeline_health_checked_at DESC);
CREATE INDEX IF NOT EXISTS strike_pipeline_health_transport_idx
    ON live_data.strike_pipeline_health (ws_transport_ok_at DESC NULLS LAST);

INSERT INTO live_data.strike_pipeline_health (
    exchange, market, symbol, pipeline_healthy, pipeline_health_reason,
    pipeline_health_checked_at, pipeline_health_max_age_sec, updated_at
)
SELECT
    exchange,
    '15m',
    symbol,
    pipeline_healthy,
    pipeline_health_reason,
    pipeline_health_checked_at,
    pipeline_health_max_age_sec,
    updated_at
FROM live_data.strike_pipeline_health_15m
ON CONFLICT (exchange, market, symbol) DO NOTHING;

DROP TABLE IF EXISTS live_data.strike_pipeline_health_15m;

-- ========== Real-time NOTIFY (statement-level for high-volume WS market writes) ==========
DROP TRIGGER IF EXISTS market_kalshi_hourly_rec_io_db_notify_stmt ON live_data.market_kalshi_hourly;
CREATE TRIGGER market_kalshi_hourly_rec_io_db_notify_stmt
    AFTER INSERT OR UPDATE OR DELETE ON live_data.market_kalshi_hourly
    FOR EACH STATEMENT
    EXECUTE PROCEDURE public.rec_io_db_notify_stmt();

DROP TRIGGER IF EXISTS strike_table_hourly_rec_io_db_notify ON live_data.strike_table_hourly;
CREATE TRIGGER strike_table_hourly_rec_io_db_notify
    AFTER INSERT OR UPDATE OR DELETE ON live_data.strike_table_hourly
    FOR EACH ROW
    EXECUTE PROCEDURE public.rec_io_db_notify();
