-- Provenance for rows archived from strike_snapshot_publisher (same ladder as Redis / AES+ATS).

ALTER TABLE historical_data.strike_table_master
    ADD COLUMN IF NOT EXISTS snapshot_wall_second BIGINT,
    ADD COLUMN IF NOT EXISTS snapshot_generation_seq BIGINT;

COMMENT ON COLUMN historical_data.strike_table_master.snapshot_wall_second IS
    'Unix epoch seconds (UTC instant) of the publisher wall second when this ladder was published to Redis; NULL for legacy generator-sourced rows.';
COMMENT ON COLUMN historical_data.strike_table_master.snapshot_generation_seq IS
    'Monotonic counter inside strike_snapshot_publisher since process start; NULL for legacy rows.';
