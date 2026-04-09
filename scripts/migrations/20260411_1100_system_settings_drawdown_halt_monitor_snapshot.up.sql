-- Persist pre-halt monitor paper_trade/test_filter snapshot for Restore Trade Operations (JSONB).
ALTER TABLE users.system_settings_0001
    ADD COLUMN IF NOT EXISTS drawdown_halt_monitor_snapshot JSONB;
