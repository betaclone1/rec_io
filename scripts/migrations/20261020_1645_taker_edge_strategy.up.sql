-- Taker Edge strategy seed.
-- One GTC at the target after a public print >= limit; dedicated taker_edge_agent (outside TE).
-- Defaults: full TTC window 0–900s, target 0.99 (min_ask = max_ask).

DO $$
DECLARE
  sch text;
  tbl text;
  new_id integer;
  has_default_col boolean;
  has_tif boolean;
  has_ot boolean;
  seq text;
  already boolean;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) AND NOT EXISTS (
    SELECT 1 FROM system.strategy_list_default WHERE name = 'Taker Edge'
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
      'Taker Edge',
      false,
      0,
      900,
      0,
      100,
      0.9900,
      0.9900,
      0,
      0.00,
      false,
      0.0000,
      false,
      false
    );
    PERFORM setval(
      pg_get_serial_sequence('system.strategy_list_default', 'id'),
      (SELECT MAX(id) FROM system.strategy_list_default)
    );
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
      AND column_name = 'time_in_force'
  ) THEN
    UPDATE system.strategy_list_default
    SET time_in_force = 'good_till_canceled'
    WHERE name = 'Taker Edge';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
      AND column_name = 'order_type'
  ) THEN
    UPDATE system.strategy_list_default
    SET order_type = 'limit'
    WHERE name = 'Taker Edge';
  END IF;

  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = sch AND table_name LIKE 'strategy_list_%'
      ORDER BY 1
    LOOP
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'default'
      ) INTO has_default_col;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'time_in_force'
      ) INTO has_tif;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'order_type'
      ) INTO has_ot;

      EXECUTE format(
        'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE name = %L)',
        sch, tbl, 'Taker Edge'
      ) INTO already;

      IF NOT already THEN
        EXECUTE format('SELECT COALESCE(MAX(id), 0) + 1 FROM %I.%I', sch, tbl) INTO new_id;

        IF has_default_col THEN
          EXECUTE format(
            'INSERT INTO %I.%I (
              id, name, "default",
              min_time, max_time, min_probability, max_probability,
              min_ask, max_ask, min_volume, min_differential,
              spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
              performance_based_allocation
            ) VALUES (
              %s, %L, false,
              0, 900, 0, 100,
              0.9900, 0.9900, 0, 0.00,
              false, 0.0000, false,
              false
            )',
            sch, tbl, new_id, 'Taker Edge'
          );
        ELSE
          EXECUTE format(
            'INSERT INTO %I.%I (
              id, name,
              min_time, max_time, min_probability, max_probability,
              min_ask, max_ask, min_volume, min_differential,
              spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
              performance_based_allocation
            ) VALUES (
              %s, %L,
              0, 900, 0, 100,
              0.9900, 0.9900, 0, 0.00,
              false, 0.0000, false,
              false
            )',
            sch, tbl, new_id, 'Taker Edge'
          );
        END IF;

        seq := pg_get_serial_sequence(format('%I.%I', sch, tbl), 'id');
        IF seq IS NOT NULL THEN
          EXECUTE format(
            'SELECT setval(%L, GREATEST((SELECT MAX(id) FROM %I.%I), 1), true)',
            seq, sch, tbl
          );
        END IF;
      END IF;

      IF has_tif THEN
        EXECUTE format(
          'UPDATE %I.%I SET time_in_force = %L WHERE name = %L',
          sch, tbl, 'good_till_canceled', 'Taker Edge'
        );
      END IF;
      IF has_ot THEN
        EXECUTE format(
          'UPDATE %I.%I SET order_type = %L WHERE name = %L',
          sch, tbl, 'limit', 'Taker Edge'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
