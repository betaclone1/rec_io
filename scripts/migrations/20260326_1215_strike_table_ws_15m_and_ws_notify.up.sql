-- WS strike table for 15m and db_change trigger for market_kalshi_ws_15m.

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

CREATE INDEX IF NOT EXISTS strike_table_ws_15m_exchange_symbol_idx
    ON live_data.strike_table_ws_15m USING btree (exchange, symbol);

CREATE INDEX IF NOT EXISTS idx_strike_table_ws_15m_lookup
    ON live_data.strike_table_ws_15m USING btree ("timestamp", symbol, current_price);

CREATE INDEX IF NOT EXISTS strike_table_ws_15m_exchange_symbol_timestamp_idx
    ON live_data.strike_table_ws_15m USING btree (exchange, symbol, "timestamp" DESC);

-- Statement-level notifier for high-frequency WS table updates.
CREATE OR REPLACE FUNCTION public.rec_io_db_notify_stmt()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM pg_notify(
    'rec_io_db_changes',
    json_build_object(
      'schema', TG_TABLE_SCHEMA,
      'table', TG_TABLE_NAME,
      'op', TG_OP
    )::text
  );
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS market_kalshi_ws_15m_rec_io_db_notify_stmt ON live_data.market_kalshi_ws_15m;
CREATE TRIGGER market_kalshi_ws_15m_rec_io_db_notify_stmt
  AFTER INSERT OR UPDATE OR DELETE ON live_data.market_kalshi_ws_15m
  FOR EACH STATEMENT
  EXECUTE PROCEDURE public.rec_io_db_notify_stmt();
