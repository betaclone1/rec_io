-- Rolling 90-minute price ring for CFB watchdog startup buffer hydration (live_data only).
-- Slim schema: timestamp + price. Not a replacement for live_price_log_1s_* retention tables.

CREATE TABLE IF NOT EXISTS live_data.live_price_ring_90m_btc (
    timestamp TEXT PRIMARY KEY,
    price NUMERIC(10, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_price_ring_90m_btc_timestamp
    ON live_data.live_price_ring_90m_btc USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_price_ring_90m_eth (
    timestamp TEXT PRIMARY KEY,
    price NUMERIC(10, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_price_ring_90m_eth_timestamp
    ON live_data.live_price_ring_90m_eth USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_price_ring_90m_sol (
    timestamp TEXT PRIMARY KEY,
    price NUMERIC(10, 6) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_price_ring_90m_sol_timestamp
    ON live_data.live_price_ring_90m_sol USING btree ("timestamp");

CREATE TABLE IF NOT EXISTS live_data.live_price_ring_90m_xrp (
    timestamp TEXT PRIMARY KEY,
    price NUMERIC(10, 6) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_live_price_ring_90m_xrp_timestamp
    ON live_data.live_price_ring_90m_xrp USING btree ("timestamp");

COMMENT ON TABLE live_data.live_price_ring_90m_btc IS
    'CFB hot-path sidecar: rolling ~90m ticks for symbol_tick_buffer hydration on watchdog restart.';
