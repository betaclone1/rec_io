DO $$
BEGIN
    -- Revert 15m pool name: active_trades_15m_<user> -> active_trades_<user>_15m
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_15m_0001'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_0001_15m'
    ) THEN
        ALTER TABLE users.active_trades_15m_0001 RENAME TO active_trades_0001_15m;
    END IF;

    -- Revert hourly pool name: active_trades_hourly_<user> -> active_trades_<user>_hourly
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_hourly_0001'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_0001_hourly'
    ) THEN
        ALTER TABLE users.active_trades_hourly_0001 RENAME TO active_trades_0001_hourly;
    END IF;

    -- Revert 15m constraint + index names.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_0001_15m'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'active_trades_15m_0001_trade_id_key'
        ) THEN
            ALTER TABLE users.active_trades_0001_15m
                RENAME CONSTRAINT active_trades_15m_0001_trade_id_key
                TO active_trades_0001_15m_trade_id_key;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'users' AND indexname = 'idx_active_trades_15m_0001_monitor_status'
        ) THEN
            ALTER INDEX users.idx_active_trades_15m_0001_monitor_status
                RENAME TO idx_active_trades_0001_15m_monitor_status;
        END IF;
    END IF;

    -- Revert hourly constraint + index names.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_0001_hourly'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'active_trades_hourly_0001_trade_id_key'
        ) THEN
            ALTER TABLE users.active_trades_0001_hourly
                RENAME CONSTRAINT active_trades_hourly_0001_trade_id_key
                TO active_trades_0001_hourly_trade_id_key;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'users' AND indexname = 'idx_active_trades_hourly_0001_monitor_status'
        ) THEN
            ALTER INDEX users.idx_active_trades_hourly_0001_monitor_status
                RENAME TO idx_active_trades_0001_hourly_monitor_status;
        END IF;
    END IF;
END
$$;
