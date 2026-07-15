-- DOGE live pipeline tables (mirror SOL/XRP high-precision decimal widths).
-- CFB index: DOGEUSD_RTI; Kalshi series: KXDOGE15M / KXDOGED.

CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_doge (
    timestamp TEXT PRIMARY KEY,
    price DECIMAL(10,6),
    one_minute_avg DECIMAL(10,6),
    momentum DECIMAL(10,4),
    delta_1m DECIMAL(10,4),
    delta_2m DECIMAL(10,4),
    delta_3m DECIMAL(10,4),
    delta_4m DECIMAL(10,4),
    delta_15m DECIMAL(10,4),
    delta_30m DECIMAL(10,4),
    momentum_percentile DECIMAL(5,1),
    momentum_5s_avg DECIMAL(5,1),
    momentum_30s_avg DECIMAL(5,1),
    volatility DECIMAL(10,6),
    volatility_percentile DECIMAL(5,1),
    move_1m DECIMAL(10,4),
    move_2m DECIMAL(10,4),
    move_3m DECIMAL(10,4),
    move_4m DECIMAL(10,4),
    move_15m DECIMAL(10,4),
    move_30m DECIMAL(10,4),
    movement DECIMAL(10,4),
    movement_percentile DECIMAL(5,1)
);

CREATE INDEX IF NOT EXISTS idx_live_price_log_1s_doge_timestamp
ON live_data.live_price_log_1s_doge USING btree (timestamp);

CREATE TABLE IF NOT EXISTS live_data.price_change_doge (
    id SERIAL PRIMARY KEY,
    change1h DECIMAL(10,6),
    change3h DECIMAL(10,6),
    change1d DECIMAL(10,6),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_data.live_price_ring_90m_doge (
    timestamp TEXT PRIMARY KEY,
    price NUMERIC(10, 6) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_price_ring_90m_doge_timestamp
    ON live_data.live_price_ring_90m_doge USING btree ("timestamp");

COMMENT ON TABLE live_data.live_price_ring_90m_doge IS
    'CFB hot-path sidecar: rolling ~90m ticks for symbol_tick_buffer hydration on watchdog restart.';

INSERT INTO live_data.symbols_list (symbol, date_added)
SELECT 'DOGE', CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM live_data.symbols_list WHERE UPPER(symbol) = 'DOGE'
);
