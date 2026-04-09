-- Trading halt latch (set TRUE when monitor_manager applies drawdown emergency halt).

ALTER TABLE users.system_settings_0001
    ADD COLUMN IF NOT EXISTS trading_halt_active BOOLEAN NOT NULL DEFAULT FALSE;
