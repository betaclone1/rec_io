-- strike_table_master: US Eastern wall (timestamp without time zone), same as other
-- historical_data time-series. New table + partitions use _mig suffix until old table is dropped.

BEGIN;

CREATE TABLE historical_data.strike_table_master_new (
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
    "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT (timezone('America/New_York', now())),
    market_result TEXT,
    PRIMARY KEY (id, "timestamp")
) PARTITION BY RANGE ("timestamp");

DO $$
DECLARE
    cur_ts timestamp;
    nxt_ts timestamp;
    part_name text;
    min_wall timestamp;
    last_wall timestamp;
    max_wall timestamp;
BEGIN
    SELECT min(("timestamp" AT TIME ZONE 'America/New_York')::timestamp)
      INTO min_wall
      FROM historical_data.strike_table_master;

    IF min_wall IS NULL THEN
        min_wall := date_trunc('month', timezone('America/New_York', now()))::timestamp;
    ELSE
        min_wall := date_trunc('month', min_wall);
    END IF;

    last_wall := date_trunc('month', timezone('America/New_York', now() + interval '5 months'))::timestamp;

    SELECT max(("timestamp" AT TIME ZONE 'America/New_York')::timestamp)
      INTO max_wall
      FROM historical_data.strike_table_master;

    IF max_wall IS NOT NULL THEN
        last_wall := greatest(
            last_wall,
            date_trunc('month', max_wall) + interval '2 months'
        );
    END IF;

    cur_ts := min_wall;
    WHILE cur_ts <= last_wall LOOP
        nxt_ts := cur_ts + interval '1 month';
        part_name := format('strike_table_master_mig%s', to_char(cur_ts, 'YYYYMM'));
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS historical_data.%I PARTITION OF historical_data.strike_table_master_new FOR VALUES FROM (%L) TO (%L)',
            part_name, cur_ts, nxt_ts
        );
        cur_ts := nxt_ts;
    END LOOP;
END $$;

INSERT INTO historical_data.strike_table_master_new (
    id, symbol, exchange, market, market_ticker, current_price, ttc_hourly, ttc_15m, event_ticker, market_title,
    strike_tier, market_status, strike, buffer, buffer_pct, probability_hourly, probability_15m,
    yes_prob_hourly, no_prob_hourly, yes_prob_15m, no_prob_15m,
    yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp, ticker, active_side,
    momentum_weighted_score, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile,
    yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m, yes_ask_range_15m, no_ask_range_15m,
    "timestamp", created_at, market_result
) OVERRIDING SYSTEM VALUE
SELECT
    id, symbol, exchange, market, market_ticker, current_price, ttc_hourly, ttc_15m, event_ticker, market_title,
    strike_tier, market_status, strike, buffer, buffer_pct, probability_hourly, probability_15m,
    yes_prob_hourly, no_prob_hourly, yes_prob_15m, no_prob_15m,
    yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
    yes_price_spread, no_price_spread, yes_diff, no_diff, volume_fp, open_interest_fp, ticker, active_side,
    momentum_weighted_score, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile,
    yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m, yes_ask_range_15m, no_ask_range_15m,
    ("timestamp" AT TIME ZONE 'America/New_York')::timestamp,
    (COALESCE(created_at, "timestamp") AT TIME ZONE 'America/New_York')::timestamp,
    market_result
FROM historical_data.strike_table_master;

DO $$
DECLARE
    seqn text;
    mx bigint;
    has_rows boolean;
BEGIN
    SELECT pg_get_serial_sequence('historical_data.strike_table_master_new', 'id') INTO seqn;
    SELECT COALESCE((SELECT MAX(id) FROM historical_data.strike_table_master_new), 1) INTO mx;
    SELECT EXISTS (SELECT 1 FROM historical_data.strike_table_master_new) INTO has_rows;
    IF seqn IS NOT NULL THEN
        PERFORM setval(seqn::regclass, mx, has_rows);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS strike_table_master_new_market_ts_idx
    ON historical_data.strike_table_master_new (market_ticker, "timestamp" DESC);
CREATE INDEX IF NOT EXISTS strike_table_master_new_symbol_market_ts_idx
    ON historical_data.strike_table_master_new (symbol, market, "timestamp" DESC);

DROP TABLE historical_data.strike_table_master CASCADE;

ALTER TABLE historical_data.strike_table_master_new RENAME TO strike_table_master;

DO $$
DECLARE
    r record;
    newname text;
BEGIN
    FOR r IN
        SELECT c.relname AS oldn
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE p.relname = 'strike_table_master'
          AND n.nspname = 'historical_data'
          AND c.relname LIKE 'strike_table_master_mig%'
    LOOP
        newname := replace(r.oldn, 'strike_table_master_mig', 'strike_table_master_');
        EXECUTE format('ALTER TABLE historical_data.%I RENAME TO %I', r.oldn, newname);
    END LOOP;
END $$;

ALTER INDEX historical_data.strike_table_master_new_market_ts_idx
    RENAME TO strike_table_master_market_ts_idx;
ALTER INDEX historical_data.strike_table_master_new_symbol_market_ts_idx
    RENAME TO strike_table_master_symbol_market_ts_idx;

DROP SCHEMA IF EXISTS migration_tmp CASCADE;

COMMIT;
