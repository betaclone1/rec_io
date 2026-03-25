-- Unified strike_table_15m: single broker column (aligned with legacy per-symbol strike tables).

ALTER TABLE live_data.strike_table_15m
    DROP COLUMN IF EXISTS exchange_display;
