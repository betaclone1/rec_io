ALTER TABLE historical_data.strike_table_master
    DROP COLUMN IF EXISTS snapshot_generation_seq,
    DROP COLUMN IF EXISTS snapshot_wall_second;
