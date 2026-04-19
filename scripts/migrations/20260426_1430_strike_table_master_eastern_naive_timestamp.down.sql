-- Lossy rollback: drops the Eastern-naive master table and recreates an empty
-- TIMESTAMPTZ + UTC-month partition layout (same shape as 20260415_1730).
-- Row data is not preserved. Use point-in-time recovery if UP ran on production.

BEGIN;

DROP TABLE IF EXISTS historical_data.strike_table_master CASCADE;

CREATE TABLE historical_data.strike_table_master (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    symbol VARCHAR(10) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    market TEXT DEFAULT '15m',
    market_ticker VARCHAR(64) NOT NULL,
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
    yes_prob_hourly DECIMAL(5,2),
    no_prob_hourly DECIMAL(5,2),
    yes_prob_15m DECIMAL(5,2),
    no_prob_15m DECIMAL(5,2),
    yes_ask_dollars TEXT,
    no_ask_dollars TEXT,
    yes_bid_dollars TEXT,
    no_bid_dollars TEXT,
    yes_price_spread NUMERIC(6,4),
    no_price_spread NUMERIC(6,4),
    yes_diff DECIMAL(5,2),
    no_diff DECIMAL(5,2),
    volume_fp TEXT,
    open_interest_fp TEXT,
    ticker VARCHAR(50),
    active_side VARCHAR(10),
    momentum_weighted_score DECIMAL(5,3),
    momentum_percentile DECIMAL(5,1),
    volatility NUMERIC(10,6),
    volatility_percentile NUMERIC(5,1),
    movement NUMERIC(10,4),
    movement_percentile NUMERIC(5,1),
    yes_ask_min_15m NUMERIC(18,4),
    yes_ask_max_15m NUMERIC(18,4),
    no_ask_min_15m NUMERIC(18,4),
    no_ask_max_15m NUMERIC(18,4),
    yes_ask_range_15m NUMERIC(18,4),
    no_ask_range_15m NUMERIC(18,4),
    "timestamp" TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    market_result TEXT,
    PRIMARY KEY (id, "timestamp")
) PARTITION BY RANGE ("timestamp");

CREATE INDEX IF NOT EXISTS strike_table_master_market_ts_idx
    ON historical_data.strike_table_master (market_ticker, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS strike_table_master_symbol_market_ts_idx
    ON historical_data.strike_table_master (symbol, market, "timestamp" DESC);

DO $$
DECLARE
    start_utc TIMESTAMPTZ;
    end_utc TIMESTAMPTZ;
    part_name TEXT;
    i INTEGER;
BEGIN
    FOR i IN 0..2 LOOP
        start_utc := (date_trunc('month', now() AT TIME ZONE 'UTC') + (i || ' months')::interval) AT TIME ZONE 'UTC';
        end_utc := (date_trunc('month', now() AT TIME ZONE 'UTC') + ((i + 1) || ' months')::interval) AT TIME ZONE 'UTC';
        part_name := format('strike_table_master_%s', to_char(start_utc AT TIME ZONE 'UTC', 'YYYYMM'));

        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS historical_data.%I PARTITION OF historical_data.strike_table_master FOR VALUES FROM (%L) TO (%L)',
            part_name,
            start_utc,
            end_utc
        );
    END LOOP;
END $$;

COMMIT;
