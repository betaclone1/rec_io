CREATE TABLE IF NOT EXISTS live_data.strike_pipeline_health_15m (
  exchange VARCHAR(20) NOT NULL,
  symbol VARCHAR(10) NOT NULL,
  pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
  pipeline_health_reason TEXT,
  pipeline_health_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 30,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (exchange, symbol)
);

CREATE INDEX IF NOT EXISTS strike_pipeline_health_15m_checked_idx
  ON live_data.strike_pipeline_health_15m (pipeline_health_checked_at DESC);
