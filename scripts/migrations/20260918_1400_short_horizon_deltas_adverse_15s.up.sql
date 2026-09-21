-- Short-horizon symbol deltas (5s/10s/15s/30s) on live_price_log_1s_* +
-- Expiration Scalp adverse_delta_15s_pct entry gate on monitor_list_*.

DO $$
DECLARE
  sch text;
  tbl text;
  col text;
BEGIN
  -- live_data.live_price_log_1s_* (BTC/ETH/SOL/XRP/DOGE/…)
  FOR tbl IN
    SELECT c.table_name
    FROM information_schema.tables c
    WHERE c.table_schema = 'live_data'
      AND c.table_name LIKE 'live_price_log_1s_%'
  LOOP
    FOREACH col IN ARRAY ARRAY['delta_5s', 'delta_10s', 'delta_15s', 'delta_30s']
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = tbl AND column_name = col
      ) THEN
        EXECUTE format(
          'ALTER TABLE live_data.%I ADD COLUMN %I NUMERIC(12,6)',
          tbl, col
        );
      END IF;
    END LOOP;
  END LOOP;

  -- live_symbol_status (legacy hub; keep shape aligned when present)
  FOREACH col IN ARRAY ARRAY['delta_5s', 'delta_10s', 'delta_15s', 'delta_30s']
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = col
    ) THEN
      EXECUTE format(
        'ALTER TABLE live_data.live_symbol_status ADD COLUMN %I NUMERIC(12,6)',
        col
      );
    END IF;
  END LOOP;

  -- monitor_list_* adverse_delta_15s_pct across users + users_NNNN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
  LOOP
    FOR tbl IN
      SELECT c.table_name
      FROM information_schema.tables c
      WHERE c.table_schema = sch AND c.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = sch AND table_name = tbl AND column_name = 'adverse_delta_15s_pct'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN adverse_delta_15s_pct NUMERIC(12,6) DEFAULT 0.000000',
          sch, tbl
        );
        EXECUTE format(
          'COMMENT ON COLUMN %I.%I.adverse_delta_15s_pct IS %L',
          sch, tbl,
          'Expiration Scalp: veto entry when spot delta_15s moves against the proposed side by at least this magnitude (percent points, same units as live delta_15s). YES vetoes on delta_15s <= -threshold; NO on delta_15s >= +threshold. 0 disables. Migration 20260918_1400_short_horizon_deltas_adverse_15s.'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
