CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_sol (
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
    move_1m DECIMAL(10,4),
    move_2m DECIMAL(10,4),
    move_3m DECIMAL(10,4),
    move_4m DECIMAL(10,4),
    move_15m DECIMAL(10,4),
    move_30m DECIMAL(10,4),
    movement DECIMAL(10,4),
    movement_percentile DECIMAL(5,1)
);

CREATE INDEX IF NOT EXISTS idx_live_price_log_1s_sol_timestamp
ON live_data.live_price_log_1s_sol USING btree (timestamp);

CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_xrp (
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
    move_1m DECIMAL(10,4),
    move_2m DECIMAL(10,4),
    move_3m DECIMAL(10,4),
    move_4m DECIMAL(10,4),
    move_15m DECIMAL(10,4),
    move_30m DECIMAL(10,4),
    movement DECIMAL(10,4),
    movement_percentile DECIMAL(5,1)
);

CREATE INDEX IF NOT EXISTS idx_live_price_log_1s_xrp_timestamp
ON live_data.live_price_log_1s_xrp USING btree (timestamp);

CREATE TABLE IF NOT EXISTS live_data.price_change_sol (
    id SERIAL PRIMARY KEY,
    change1h DECIMAL(10,6),
    change3h DECIMAL(10,6),
    change1d DECIMAL(10,6),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_data.price_change_xrp (
    id SERIAL PRIMARY KEY,
    change1h DECIMAL(10,6),
    change3h DECIMAL(10,6),
    change1d DECIMAL(10,6),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
