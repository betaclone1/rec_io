-- Reverse 20260329_2359: split unified hourly tables; restore strike_pipeline_health_15m.

DROP TRIGGER IF EXISTS strike_table_hourly_rec_io_db_notify ON live_data.strike_table_hourly;
DROP TRIGGER IF EXISTS market_kalshi_hourly_rec_io_db_notify_stmt ON live_data.market_kalshi_hourly;

CREATE TABLE IF NOT EXISTS live_data.strike_pipeline_health_15m (
    exchange VARCHAR(20) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
    pipeline_health_reason TEXT,
    pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 900,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol)
);

INSERT INTO live_data.strike_pipeline_health_15m (
    exchange, symbol, pipeline_healthy, pipeline_health_reason,
    pipeline_health_checked_at, pipeline_health_max_age_sec, updated_at
)
SELECT
    exchange, symbol, pipeline_healthy, pipeline_health_reason,
    pipeline_health_checked_at, pipeline_health_max_age_sec, updated_at
FROM live_data.strike_pipeline_health
WHERE market = '15m'
ON CONFLICT (exchange, symbol) DO UPDATE SET
    pipeline_healthy = EXCLUDED.pipeline_healthy,
    pipeline_health_reason = EXCLUDED.pipeline_health_reason,
    pipeline_health_checked_at = EXCLUDED.pipeline_health_checked_at,
    pipeline_health_max_age_sec = EXCLUDED.pipeline_health_max_age_sec,
    updated_at = EXCLUDED.updated_at;

CREATE INDEX IF NOT EXISTS strike_pipeline_health_15m_checked_idx
    ON live_data.strike_pipeline_health_15m (pipeline_health_checked_at DESC);

DROP TABLE IF EXISTS live_data.strike_pipeline_health;

-- Split market_kalshi_hourly -> btc / eth (staging names avoid duplicate constraint names while source exists)
CREATE TABLE live_data._mk_h_btc (
    LIKE live_data.market_kalshi_hourly
    INCLUDING DEFAULTS
    INCLUDING CONSTRAINTS
    INCLUDING IDENTITY
);
CREATE TABLE live_data._mk_h_eth (
    LIKE live_data.market_kalshi_hourly
    INCLUDING DEFAULTS
    INCLUDING CONSTRAINTS
    INCLUDING IDENTITY
);

INSERT INTO live_data._mk_h_btc SELECT * FROM live_data.market_kalshi_hourly WHERE symbol = 'BTC';
INSERT INTO live_data._mk_h_eth SELECT * FROM live_data.market_kalshi_hourly WHERE symbol = 'ETH';

DROP TABLE IF EXISTS live_data.market_kalshi_hourly CASCADE;

ALTER TABLE live_data._mk_h_btc RENAME TO market_kalshi_hourly_btc;
ALTER TABLE live_data._mk_h_eth RENAME TO market_kalshi_hourly_eth;

SELECT setval(
    pg_get_serial_sequence('live_data.market_kalshi_hourly_btc', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data.market_kalshi_hourly_btc), 1)
);
SELECT setval(
    pg_get_serial_sequence('live_data.market_kalshi_hourly_eth', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data.market_kalshi_hourly_eth), 1)
);

CREATE INDEX IF NOT EXISTS market_kalshi_hourly_btc_exchange_symbol_idx
    ON live_data.market_kalshi_hourly_btc (exchange, symbol);
CREATE INDEX IF NOT EXISTS market_kalshi_hourly_btc_exchange_symbol_event_idx
    ON live_data.market_kalshi_hourly_btc (exchange, symbol, event_ticker);
CREATE INDEX IF NOT EXISTS market_kalshi_hourly_eth_exchange_symbol_idx
    ON live_data.market_kalshi_hourly_eth (exchange, symbol);
CREATE INDEX IF NOT EXISTS market_kalshi_hourly_eth_exchange_symbol_event_idx
    ON live_data.market_kalshi_hourly_eth (exchange, symbol, event_ticker);

-- Split strike_table_hourly -> btc / eth
CREATE TABLE live_data._st_h_btc (
    LIKE live_data.strike_table_hourly
    INCLUDING DEFAULTS
    INCLUDING CONSTRAINTS
    INCLUDING IDENTITY
);
CREATE TABLE live_data._st_h_eth (
    LIKE live_data.strike_table_hourly
    INCLUDING DEFAULTS
    INCLUDING CONSTRAINTS
    INCLUDING IDENTITY
);

INSERT INTO live_data._st_h_btc (
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
FROM live_data.strike_table_hourly WHERE symbol = 'BTC';

INSERT INTO live_data._st_h_eth (
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
FROM live_data.strike_table_hourly WHERE symbol = 'ETH';

DROP TABLE IF EXISTS live_data.strike_table_hourly CASCADE;

ALTER TABLE live_data._st_h_btc RENAME TO strike_table_hourly_btc;
ALTER TABLE live_data._st_h_eth RENAME TO strike_table_hourly_eth;

SELECT setval(
    pg_get_serial_sequence('live_data.strike_table_hourly_btc', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data.strike_table_hourly_btc), 1)
);
SELECT setval(
    pg_get_serial_sequence('live_data.strike_table_hourly_eth', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data.strike_table_hourly_eth), 1)
);

CREATE INDEX IF NOT EXISTS idx_strike_table_hourly_btc_lookup
    ON live_data.strike_table_hourly_btc ("timestamp", symbol, current_price);
CREATE INDEX IF NOT EXISTS strike_table_hourly_btc_exchange_symbol_idx
    ON live_data.strike_table_hourly_btc (exchange, symbol);
CREATE INDEX IF NOT EXISTS strike_table_hourly_btc_exchange_symbol_timestamp_idx
    ON live_data.strike_table_hourly_btc (exchange, symbol, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_strike_table_hourly_eth_lookup
    ON live_data.strike_table_hourly_eth ("timestamp", symbol, current_price);
CREATE INDEX IF NOT EXISTS strike_table_hourly_eth_exchange_symbol_idx
    ON live_data.strike_table_hourly_eth (exchange, symbol);
CREATE INDEX IF NOT EXISTS strike_table_hourly_eth_exchange_symbol_timestamp_idx
    ON live_data.strike_table_hourly_eth (exchange, symbol, "timestamp" DESC);
