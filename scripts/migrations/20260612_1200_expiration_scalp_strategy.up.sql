-- Seed "Expiration Scalp" strategy defaults in system.strategy_list_default and all tenant strategy_list_* tables.
-- Near-expiration entry: TTC window, active-side ask range, probability band; no auto-stop behavior.

DO $$
DECLARE
  sch text;
  tbl text;
  new_id integer;
  has_default_col boolean;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM system.strategy_list_default WHERE name = 'Expiration Scalp'
  ) THEN
    SELECT COALESCE(MAX(id), 0) + 1 INTO new_id FROM system.strategy_list_default;
    INSERT INTO system.strategy_list_default (
      id,
      name,
      "default",
      min_time,
      max_time,
      min_probability,
      max_probability,
      min_ask,
      max_ask,
      min_volume,
      min_differential,
      spike_alert_enabled,
      stop_loss_price,
      loss_prevention_toggle,
      performance_based_allocation
    ) VALUES (
      new_id,
      'Expiration Scalp',
      false,
      0,
      60,
      90,
      100,
      0.9000,
      0.9900,
      0,
      0.00,
      false,
      0.9900,
      false,
      false
    );
    PERFORM setval(
      pg_get_serial_sequence('system.strategy_list_default', 'id'),
      (SELECT MAX(id) FROM system.strategy_list_default)
    );
  END IF;

  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = sch
        AND table_name LIKE 'strategy_list_%'
      ORDER BY 1
    LOOP
      SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = sch
          AND c.table_name = tbl
          AND c.column_name = 'default'
      ) INTO has_default_col;

      IF has_default_col THEN
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name,
            "default",
            min_time,
            max_time,
            min_probability,
            max_probability,
            min_ask,
            max_ask,
            min_volume,
            min_differential,
            spike_alert_enabled,
            stop_loss_price,
            loss_prevention_toggle,
            performance_based_allocation
          )
          SELECT
            'Expiration Scalp',
            false,
            0,
            60,
            90,
            100,
            0.9000,
            0.9900,
            0,
            0.00,
            false,
            0.9900,
            false,
            false
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'Expiration Scalp'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      ELSE
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name,
            min_time,
            max_time,
            min_probability,
            max_probability,
            min_ask,
            max_ask,
            min_volume,
            min_differential,
            spike_alert_enabled,
            stop_loss_price,
            loss_prevention_toggle,
            performance_based_allocation
          )
          SELECT
            'Expiration Scalp',
            0,
            60,
            90,
            100,
            0.9000,
            0.9900,
            0,
            0.00,
            false,
            0.9900,
            false,
            false
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'Expiration Scalp'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
