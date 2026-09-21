-- Revert short-horizon deltas and adverse_delta_15s_pct.

DO $$
DECLARE
  sch text;
  tbl text;
  col text;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
  LOOP
    FOR tbl IN
      SELECT c.table_name
      FROM information_schema.tables c
      WHERE c.table_schema = sch AND c.table_name LIKE 'monitor_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = sch AND table_name = tbl AND column_name = 'adverse_delta_15s_pct'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN adverse_delta_15s_pct', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;

  FOR tbl IN
    SELECT c.table_name
    FROM information_schema.tables c
    WHERE c.table_schema = 'live_data'
      AND c.table_name LIKE 'live_price_log_1s_%'
  LOOP
    FOREACH col IN ARRAY ARRAY['delta_5s', 'delta_10s', 'delta_15s', 'delta_30s']
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'live_data' AND table_name = tbl AND column_name = col
      ) THEN
        EXECUTE format('ALTER TABLE live_data.%I DROP COLUMN %I', tbl, col);
      END IF;
    END LOOP;
  END LOOP;

  FOREACH col IN ARRAY ARRAY['delta_5s', 'delta_10s', 'delta_15s', 'delta_30s']
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'live_data' AND table_name = 'live_symbol_status' AND column_name = col
    ) THEN
      EXECUTE format('ALTER TABLE live_data.live_symbol_status DROP COLUMN %I', col);
    END IF;
  END LOOP;
END $$;
