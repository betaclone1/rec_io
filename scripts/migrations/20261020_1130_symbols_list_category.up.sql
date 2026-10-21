-- Symbol category drives which live-data package a monitor must have healthy.
-- crypto: full strike/market WS + spot (existing strike_pipeline_health gate)
-- commodity: market meta + public trades + pyth spot (commodity_pipeline_health + spot gate)

ALTER TABLE live_data.symbols_list
  ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'crypto';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'symbols_list_category_check'
      AND conrelid = 'live_data.symbols_list'::regclass
  ) THEN
    ALTER TABLE live_data.symbols_list
      ADD CONSTRAINT symbols_list_category_check
      CHECK (category IN ('crypto', 'commodity'));
  END IF;
END $$;

COMMENT ON COLUMN live_data.symbols_list.category IS
  'Live-data pipeline package: crypto (full strike/market/spot) or commodity (market meta + public trades + pyth spot).';

-- Existing rows inherit DEFAULT 'crypto' from ADD COLUMN.

CREATE TABLE IF NOT EXISTS live_data.commodity_pipeline_health (
  exchange VARCHAR(20) NOT NULL,
  market VARCHAR(20) NOT NULL,
  symbol VARCHAR(10) NOT NULL,
  pipeline_healthy BOOLEAN NOT NULL DEFAULT FALSE,
  pipeline_health_reason TEXT,
  pipeline_health_checked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  pipeline_health_max_age_sec INTEGER NOT NULL DEFAULT 900,
  ws_transport_ok_at TIMESTAMP WITH TIME ZONE,
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  PRIMARY KEY (exchange, market, symbol)
);

CREATE INDEX IF NOT EXISTS commodity_pipeline_health_checked_idx
  ON live_data.commodity_pipeline_health USING btree (pipeline_health_checked_at DESC);

CREATE INDEX IF NOT EXISTS commodity_pipeline_health_transport_idx
  ON live_data.commodity_pipeline_health USING btree (ws_transport_ok_at DESC NULLS LAST);

COMMENT ON TABLE live_data.commodity_pipeline_health IS
  'Lean commodity package health: market meta + public trades WS. Spot/pyth checked at gate via live_state/ring. Keyed by (exchange, market, symbol).';
