-- Live price feed hygiene:
-- Watchdog writes derived fields into live_data.live_price_log_1s_btc / _eth.
-- Postgres triggers keep live_data.live_symbol_status in sync from the newest log row.
-- This removes the second Python-side write from symbol_price_watchdog.py.

-- Ensure exactly one row per symbol so triggers can upsert deterministically.
CREATE UNIQUE INDEX IF NOT EXISTS live_symbol_status_symbol_uniq
ON live_data.live_symbol_status USING btree (symbol)
WHERE symbol IS NOT NULL;

-- BTC: sync latest tick-derived fields into the symbol status row.
CREATE OR REPLACE FUNCTION live_data.trg_sync_live_symbol_status_btc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO live_data.live_symbol_status (
        symbol,
        "timestamp",
        price,
        one_minute_avg,
        momentum,
        delta_1m,
        delta_2m,
        delta_3m,
        delta_4m,
        delta_15m,
        delta_30m,
        momentum_percentile,
        momentum_5s_avg,
        volatility,
        volatility_percentile,
        momentum_30s_avg,
        move_1m,
        move_2m,
        move_3m,
        move_4m,
        move_15m,
        move_30m,
        movement,
        movement_percentile
    )
    VALUES (
        'BTC',
        NEW.timestamp,
        NEW.price,
        NEW.one_minute_avg,
        NEW.momentum,
        NEW.delta_1m,
        NEW.delta_2m,
        NEW.delta_3m,
        NEW.delta_4m,
        NEW.delta_15m,
        NEW.delta_30m,
        NEW.momentum_percentile,
        NEW.momentum_5s_avg,
        NEW.volatility,
        NEW.volatility_percentile,
        NEW.momentum_30s_avg,
        NEW.move_1m,
        NEW.move_2m,
        NEW.move_3m,
        NEW.move_4m,
        NEW.move_15m,
        NEW.move_30m,
        NEW.movement,
        NEW.movement_percentile
    )
    ON CONFLICT (symbol) DO UPDATE SET
        "timestamp" = EXCLUDED."timestamp",
        price = EXCLUDED.price,
        one_minute_avg = EXCLUDED.one_minute_avg,
        momentum = EXCLUDED.momentum,
        delta_1m = EXCLUDED.delta_1m,
        delta_2m = EXCLUDED.delta_2m,
        delta_3m = EXCLUDED.delta_3m,
        delta_4m = EXCLUDED.delta_4m,
        delta_15m = EXCLUDED.delta_15m,
        delta_30m = EXCLUDED.delta_30m,
        momentum_percentile = EXCLUDED.momentum_percentile,
        momentum_5s_avg = EXCLUDED.momentum_5s_avg,
        volatility = EXCLUDED.volatility,
        volatility_percentile = EXCLUDED.volatility_percentile,
        momentum_30s_avg = EXCLUDED.momentum_30s_avg,
        move_1m = EXCLUDED.move_1m,
        move_2m = EXCLUDED.move_2m,
        move_3m = EXCLUDED.move_3m,
        move_4m = EXCLUDED.move_4m,
        move_15m = EXCLUDED.move_15m,
        move_30m = EXCLUDED.move_30m,
        movement = EXCLUDED.movement,
        movement_percentile = EXCLUDED.movement_percentile;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_live_symbol_status_btc_from_price_log ON live_data.live_price_log_1s_btc;
CREATE TRIGGER sync_live_symbol_status_btc_from_price_log
AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_btc
FOR EACH ROW
EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_btc();

-- ETH: sync latest tick-derived fields into the symbol status row.
CREATE OR REPLACE FUNCTION live_data.trg_sync_live_symbol_status_eth()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO live_data.live_symbol_status (
        symbol,
        "timestamp",
        price,
        one_minute_avg,
        momentum,
        delta_1m,
        delta_2m,
        delta_3m,
        delta_4m,
        delta_15m,
        delta_30m,
        momentum_percentile,
        momentum_5s_avg,
        volatility,
        volatility_percentile,
        momentum_30s_avg,
        move_1m,
        move_2m,
        move_3m,
        move_4m,
        move_15m,
        move_30m,
        movement,
        movement_percentile
    )
    VALUES (
        'ETH',
        NEW.timestamp,
        NEW.price,
        NEW.one_minute_avg,
        NEW.momentum,
        NEW.delta_1m,
        NEW.delta_2m,
        NEW.delta_3m,
        NEW.delta_4m,
        NEW.delta_15m,
        NEW.delta_30m,
        NEW.momentum_percentile,
        NEW.momentum_5s_avg,
        NEW.volatility,
        NEW.volatility_percentile,
        NEW.momentum_30s_avg,
        NEW.move_1m,
        NEW.move_2m,
        NEW.move_3m,
        NEW.move_4m,
        NEW.move_15m,
        NEW.move_30m,
        NEW.movement,
        NEW.movement_percentile
    )
    ON CONFLICT (symbol) DO UPDATE SET
        "timestamp" = EXCLUDED."timestamp",
        price = EXCLUDED.price,
        one_minute_avg = EXCLUDED.one_minute_avg,
        momentum = EXCLUDED.momentum,
        delta_1m = EXCLUDED.delta_1m,
        delta_2m = EXCLUDED.delta_2m,
        delta_3m = EXCLUDED.delta_3m,
        delta_4m = EXCLUDED.delta_4m,
        delta_15m = EXCLUDED.delta_15m,
        delta_30m = EXCLUDED.delta_30m,
        momentum_percentile = EXCLUDED.momentum_percentile,
        momentum_5s_avg = EXCLUDED.momentum_5s_avg,
        volatility = EXCLUDED.volatility,
        volatility_percentile = EXCLUDED.volatility_percentile,
        momentum_30s_avg = EXCLUDED.momentum_30s_avg,
        move_1m = EXCLUDED.move_1m,
        move_2m = EXCLUDED.move_2m,
        move_3m = EXCLUDED.move_3m,
        move_4m = EXCLUDED.move_4m,
        move_15m = EXCLUDED.move_15m,
        move_30m = EXCLUDED.move_30m,
        movement = EXCLUDED.movement,
        movement_percentile = EXCLUDED.movement_percentile;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sync_live_symbol_status_eth_from_price_log ON live_data.live_price_log_1s_eth;
CREATE TRIGGER sync_live_symbol_status_eth_from_price_log
AFTER INSERT OR UPDATE ON live_data.live_price_log_1s_eth
FOR EACH ROW
EXECUTE FUNCTION live_data.trg_sync_live_symbol_status_eth();

