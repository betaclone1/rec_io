-- Durable audit trail for ATS stop-loss coverage (enrollment, ticks, reconciliation).
CREATE TABLE IF NOT EXISTS users.ats_monitoring_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trade_id INTEGER,
    monitor_key TEXT,
    stage TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT,
    detail JSONB,
    source TEXT NOT NULL DEFAULT 'unknown'
);

CREATE INDEX IF NOT EXISTS idx_ats_monitoring_events_trade_created
    ON users.ats_monitoring_events (trade_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ats_monitoring_events_stage_created
    ON users.ats_monitoring_events (stage, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ats_monitoring_events_reason_created
    ON users.ats_monitoring_events (reason_code, created_at DESC)
    WHERE reason_code IS NOT NULL;
