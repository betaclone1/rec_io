-- Maker Edge strategy seed.
-- Dual BID/ASK resting GTC at monitor limit; dedicated maker_edge_agent (outside TE).
-- Defaults: full TTC window 0–900s, limit 0.01 (min_ask = max_ask).

DO $$
DECLARE
  sch text;
  tbl text;
  new_id integer;
  has_default_col boolean;
  has_tif boolean;
  has_ot boolean;
BEGIN
  -- Seed system.strategy_list_default
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) AND NOT EXISTS (
    SELECT 1 FROM system.strategy_list_default WHERE name = 'Maker Edge'
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
      'Maker Edge',
      false,
      0,
      900,
      0,
      100,
      0.0100,
      0.0100,
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
    WHERE name = 'Maker Edge'
      AND (time_in_force IS NULL OR BTRIM(time_in_force) = '');
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
      AND column_name = 'order_type'
  ) THEN
    UPDATE system.strategy_list_default
    SET order_type = 'limit'
    WHERE name = 'Maker Edge'
      AND (order_type IS NULL OR BTRIM(order_type) = '');
  END IF;

  -- Seed tenant strategy_list_*
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

      IF has_default_col THEN
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name, "default",
            min_time, max_time, min_probability, max_probability,
            min_ask, max_ask, min_volume, min_differential,
            spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
            performance_based_allocation
          )
          SELECT
            'Maker Edge', false,
            0, 900, 0, 100,
            0.0100, 0.0100, 0, 0.00,
            false, 0.0000, false,
            false
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'Maker Edge'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      ELSE
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name,
            min_time, max_time, min_probability, max_probability,
            min_ask, max_ask, min_volume, min_differential,
            spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
            performance_based_allocation
          )
          SELECT
            'Maker Edge',
            0, 900, 0, 100,
            0.0100, 0.0100, 0, 0.00,
            false, 0.0000, false,
            false
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'Maker Edge'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      END IF;

      IF has_tif THEN
        EXECUTE format(
          'UPDATE %I.%I SET time_in_force = %L
           WHERE name = %L AND (time_in_force IS NULL OR BTRIM(time_in_force) = %L)',
          sch, tbl, 'good_till_canceled', 'Maker Edge', ''
        );
      END IF;
      IF has_ot THEN
        EXECUTE format(
          'UPDATE %I.%I SET order_type = %L
           WHERE name = %L AND (order_type IS NULL OR BTRIM(order_type) = %L)',
          sch, tbl, 'limit', 'Maker Edge', ''
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
