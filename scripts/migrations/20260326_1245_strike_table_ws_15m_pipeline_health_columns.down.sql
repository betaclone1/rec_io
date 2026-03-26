DROP INDEX IF EXISTS live_data.strike_table_ws_15m_exchange_symbol_health_checked_idx;

ALTER TABLE live_data.strike_table_ws_15m
  DROP COLUMN IF EXISTS pipeline_health_max_age_sec,
  DROP COLUMN IF EXISTS pipeline_health_checked_at,
  DROP COLUMN IF EXISTS pipeline_health_reason,
  DROP COLUMN IF EXISTS pipeline_healthy;
