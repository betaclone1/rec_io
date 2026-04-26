-- Reverse 20260426_1600_monitor_trades_execution_settings.up.sql
DO $$
DECLARE
  sch text;
  ml_tbl text;
  tr_tbl text;
  sim_tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR ml_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^monitor_list_'
    LOOP
      EXECUTE format(
        'ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I',
        sch, ml_tbl, ml_tbl || '_order_type_policy_chk'
      );
      EXECUTE format(
        'ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I',
        sch, ml_tbl, ml_tbl || '_time_in_force_chk'
      );
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN IF EXISTS order_type',
        sch, ml_tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN IF EXISTS time_in_force',
        sch, ml_tbl
      );
    END LOOP;

    IF sch = 'users' THEN
      tr_tbl := 'trades_0001';
      sim_tbl := 'trades_simulated_0001';
    ELSE
      tr_tbl := 'trades_' || right(sch, 4);
      sim_tbl := 'trades_simulated_' || right(sch, 4);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = sch AND table_name = tr_tbl
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS order_type', sch, tr_tbl);
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS time_in_force', sch, tr_tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = sch AND table_name = sim_tbl
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS order_type', sch, sim_tbl);
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS time_in_force', sch, sim_tbl);
    END IF;
  END LOOP;
END $$;
