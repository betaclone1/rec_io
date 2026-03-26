ALTER TABLE live_data.strike_table_ws_15m
  ADD COLUMN IF NOT EXISTS pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS pipeline_health_reason TEXT,
  ADD COLUMN IF NOT EXISTS pipeline_health_checked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 30;

CREATE INDEX IF NOT EXISTS strike_table_ws_15m_exchange_symbol_health_checked_idx
  ON live_data.strike_table_ws_15m USING btree (exchange, symbol, pipeline_health_checked_at DESC);
