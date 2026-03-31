DO $$
BEGIN
    -- 15m pool: active_trades_<user>_15m -> active_trades_15m_<user>
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_0001_15m'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_15m_0001'
    ) THEN
        ALTER TABLE users.active_trades_0001_15m RENAME TO active_trades_15m_0001;
    END IF;

    -- hourly pool: active_trades_<user>_hourly -> active_trades_hourly_<user>
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_0001_hourly'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_hourly_0001'
    ) THEN
        ALTER TABLE users.active_trades_0001_hourly RENAME TO active_trades_hourly_0001;
    END IF;

    -- Normalize 15m unique constraint + index names to match new table naming.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_15m_0001'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'active_trades_0001_15m_trade_id_key'
        ) THEN
            ALTER TABLE users.active_trades_15m_0001
                RENAME CONSTRAINT active_trades_0001_15m_trade_id_key
                TO active_trades_15m_0001_trade_id_key;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'users' AND indexname = 'idx_active_trades_0001_15m_monitor_status'
        ) THEN
            ALTER INDEX users.idx_active_trades_0001_15m_monitor_status
                RENAME TO idx_active_trades_15m_0001_monitor_status;
        END IF;
    END IF;

    -- Normalize hourly unique constraint + index names to match new table naming.
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'users' AND table_name = 'active_trades_hourly_0001'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'active_trades_0001_hourly_trade_id_key'
        ) THEN
            ALTER TABLE users.active_trades_hourly_0001
                RENAME CONSTRAINT active_trades_0001_hourly_trade_id_key
                TO active_trades_hourly_0001_trade_id_key;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'users' AND indexname = 'idx_active_trades_0001_hourly_monitor_status'
        ) THEN
            ALTER INDEX users.idx_active_trades_0001_hourly_monitor_status
                RENAME TO idx_active_trades_hourly_0001_monitor_status;
        END IF;
    END IF;
END
$$;
