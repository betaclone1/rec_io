-- Master system event log: append-only high-level operational timeline (EST wall timestamps).

CREATE TABLE IF NOT EXISTS system.event_log (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    category    TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'info'
                CHECK (severity IN ('info', 'warning', 'critical')),
    source      TEXT NOT NULL,
    message     TEXT NOT NULL,
    detail_ref  TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS event_log_timestamp_idx ON system.event_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS event_log_category_idx ON system.event_log (category);

COMMENT ON TABLE system.event_log IS
    'High-level system events for admin timeline (restarts, halts, deploys, WS issues). EST wall time in timestamp.';
