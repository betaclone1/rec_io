-- Last successful ATS telemetry refresh for open trades (mark-to-market path).
ALTER TABLE users.trades_0001
    ADD COLUMN IF NOT EXISTS ats_updated TIMESTAMPTZ;

ALTER TABLE users.trades_simulated_0001
    ADD COLUMN IF NOT EXISTS ats_updated TIMESTAMPTZ;

COMMENT ON COLUMN users.trades_0001.ats_updated IS
    'Set when ATS successfully joins strike data and updates live telemetry (pnl, ask min/max/range, etc.).';
