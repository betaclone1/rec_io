-- Per-user global/system settings (user 0001). Singleton row id=1.

CREATE TABLE users.system_settings_0001 (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    drawdown_trading_halt BOOLEAN NOT NULL DEFAULT TRUE,
    drawdown_reset_threshold_pct NUMERIC(5, 2) NOT NULL DEFAULT 50.00
        CHECK (drawdown_reset_threshold_pct > 0 AND drawdown_reset_threshold_pct < 100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO users.system_settings_0001 (id, drawdown_trading_halt, drawdown_reset_threshold_pct)
VALUES (1, TRUE, 50.00)
ON CONFLICT (id) DO NOTHING;
