-- Physical column order and types for unified hourly tables match market_kalshi_15m / strike_table_15m
-- (migration 20260329_2359 merged legacy hourly tables with a different ordinal layout).

-- ========== strike_table_hourly ==========
CREATE TABLE live_data._strike_hourly_align (
    LIKE live_data.strike_table_15m
    INCLUDING DEFAULTS
    INCLUDING IDENTITY
);

ALTER TABLE live_data._strike_hourly_align
    ADD CONSTRAINT _strike_hourly_align_pkey PRIMARY KEY (id);

INSERT INTO live_data._strike_hourly_align (
    id, "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
    event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
    probability_hourly, probability_15m, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, ticker, active_side, momentum_weighted_score,
    momentum_percentile, volatility, volatility_percentile, movement, movement_percentile, created_at,
    yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m, yes_ask_range_15m, no_ask_range_15m,
    volume_fp, open_interest_fp
)
SELECT
    id, "timestamp", symbol, exchange, market, current_price, ttc_hourly, ttc_15m,
    event_ticker, market_title, strike_tier, market_status, strike, buffer, buffer_pct,
    probability_hourly, probability_15m, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, ticker, active_side, momentum_weighted_score,
    momentum_percentile, volatility, volatility_percentile, movement, movement_percentile, created_at,
    yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m, yes_ask_range_15m, no_ask_range_15m,
    volume_fp, open_interest_fp
FROM live_data.strike_table_hourly;

SELECT setval(
    pg_get_serial_sequence('live_data._strike_hourly_align', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data._strike_hourly_align), 1)
);

DROP TRIGGER IF EXISTS strike_table_hourly_rec_io_db_notify ON live_data.strike_table_hourly;
DROP TABLE IF EXISTS live_data.strike_table_hourly CASCADE;

ALTER TABLE live_data._strike_hourly_align RENAME TO strike_table_hourly;

CREATE INDEX IF NOT EXISTS idx_strike_table_hourly_lookup
    ON live_data.strike_table_hourly ("timestamp", symbol, current_price);
CREATE INDEX IF NOT EXISTS strike_table_hourly_exchange_symbol_idx
    ON live_data.strike_table_hourly (exchange, symbol);
CREATE INDEX IF NOT EXISTS strike_table_hourly_exchange_symbol_timestamp_idx
    ON live_data.strike_table_hourly (exchange, symbol, "timestamp" DESC);

CREATE TRIGGER strike_table_hourly_rec_io_db_notify
    AFTER INSERT OR UPDATE OR DELETE ON live_data.strike_table_hourly
    FOR EACH ROW
    EXECUTE PROCEDURE public.rec_io_db_notify();

-- ========== market_kalshi_hourly ==========
CREATE TABLE live_data._mk_hourly_align (
    LIKE live_data.market_kalshi_15m
    INCLUDING DEFAULTS
    INCLUDING IDENTITY
);

ALTER TABLE live_data._mk_hourly_align ADD CONSTRAINT _mk_hourly_align_pkey PRIMARY KEY (id);

-- Staging name avoids collision with existing market_kalshi_hourly_* index names before DROP.
ALTER TABLE live_data._mk_hourly_align
    ADD CONSTRAINT _mk_hourly_staging_uq
    UNIQUE (exchange, symbol, event_ticker, market_ticker);

INSERT INTO live_data._mk_hourly_align (
    id, symbol, exchange, event_ticker, market_ticker, market, strike,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
    volume_fp, created_at, updated_at, open_interest_fp
)
SELECT
    id, symbol, exchange, event_ticker, market_ticker, market, strike,
    yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
    volume_fp, created_at, updated_at, open_interest_fp
FROM live_data.market_kalshi_hourly;

SELECT setval(
    pg_get_serial_sequence('live_data._mk_hourly_align', 'id'),
    COALESCE((SELECT MAX(id) FROM live_data._mk_hourly_align), 1)
);

DROP TRIGGER IF EXISTS market_kalshi_hourly_rec_io_db_notify_stmt ON live_data.market_kalshi_hourly;
DROP TABLE IF EXISTS live_data.market_kalshi_hourly CASCADE;

ALTER TABLE live_data._mk_hourly_align RENAME TO market_kalshi_hourly;

ALTER TABLE live_data.market_kalshi_hourly
    RENAME CONSTRAINT _mk_hourly_staging_uq TO market_kalshi_hourly_ex_sym_evt_mkt_uniq;

CREATE INDEX IF NOT EXISTS market_kalshi_hourly_exchange_symbol_idx
    ON live_data.market_kalshi_hourly (exchange, symbol);
CREATE INDEX IF NOT EXISTS market_kalshi_hourly_exchange_symbol_event_idx
    ON live_data.market_kalshi_hourly (exchange, symbol, event_ticker);

CREATE TRIGGER market_kalshi_hourly_rec_io_db_notify_stmt
    AFTER INSERT OR UPDATE OR DELETE ON live_data.market_kalshi_hourly
    FOR EACH STATEMENT
    EXECUTE PROCEDURE public.rec_io_db_notify_stmt();
