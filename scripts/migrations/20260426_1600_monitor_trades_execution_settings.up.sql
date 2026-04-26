-- Per-monitor Kalshi execution: time_in_force (Kalshi enum) and order_type (limit|market policy).
-- Trades rows snapshot the same for confirm/close paths. Reversible via .down.sql.
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
    -- monitor_list_<slot>
    FOR ml_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^monitor_list_'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'time_in_force'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN time_in_force TEXT NOT NULL DEFAULT %L',
          sch, ml_tbl, 'fill_or_kill'
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (time_in_force IN (%L, %L, %L))',
          sch, ml_tbl,
          ml_tbl || '_time_in_force_chk',
          'fill_or_kill', 'immediate_or_cancel', 'good_till_canceled'
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'order_type'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN order_type TEXT NOT NULL DEFAULT %L',
          sch, ml_tbl, 'market'
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (order_type IN (%L, %L))',
          sch, ml_tbl,
          ml_tbl || '_order_type_policy_chk',
          'limit', 'market'
        );
      END IF;
    END LOOP;

    -- trades_<slot> + trades_simulated_<slot>
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
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tr_tbl AND c.column_name = 'time_in_force'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN time_in_force TEXT',
          sch, tr_tbl
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tr_tbl AND c.column_name = 'order_type'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN order_type TEXT',
          sch, tr_tbl
        );
      END IF;
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = sch AND table_name = sim_tbl
    ) THEN
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = sim_tbl AND c.column_name = 'time_in_force'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN time_in_force TEXT',
          sch, sim_tbl
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = sim_tbl AND c.column_name = 'order_type'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN order_type TEXT',
          sch, sim_tbl
        );
      END IF;
    END IF;
  END LOOP;
END $$;
