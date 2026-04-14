-- Append-only deployment version history (current version = latest row by id).
CREATE TABLE IF NOT EXISTS system.version_control (
    id SERIAL PRIMARY KEY,
    version VARCHAR(32) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE system.version_control IS
    'One row per production (or notable) deploy: semantic version and when it was recorded.';

CREATE INDEX IF NOT EXISTS version_control_updated_at_idx
    ON system.version_control (updated_at DESC);

INSERT INTO system.version_control (version, updated_at)
SELECT '3.0.1', NOW()
WHERE NOT EXISTS (SELECT 1 FROM system.version_control);
