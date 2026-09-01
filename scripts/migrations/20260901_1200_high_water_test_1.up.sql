-- High Water Test 1: limit_close_offset on monitor/strategy/trade snapshot.
-- Profit GTC target = buy_price + offset (owned-side); limit_close_price on trade row
-- is computed at fill confirm. High Water Scalp keeps absolute limit_close_price.

DO $$
DECLARE
  sch text;
  tbl text;
  new_id integer;
  has_default_col boolean;
  has_lcp boolean;
  has_lco boolean;
  has_tif boolean;
  has_ot boolean;
  has_verify_en boolean;
  has_verify_sec boolean;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN limit_close_offset NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.limit_close_offset IS %L',
        sch, tbl,
        'High Water Test 1: owned-side GTC close offset from fill (e.g. 0.0100). 0 disables. Migration 20260901_1200_high_water_test_1.'
      );
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN limit_close_offset NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN limit_close_offset NUMERIC(6,4) NOT NULL DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'limit_close_offset'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN limit_close_offset NUMERIC(6,4) DEFAULT 0.0000;
    END IF;
  END IF;

  FOR tbl IN
    SELECT t.table_name FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS limit_close_offset NUMERIC(6,4)',
      tbl
    );
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) AND NOT EXISTS (
    SELECT 1 FROM system.strategy_list_default WHERE name = 'High Water Test 1'
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
      performance_based_allocation,
      limit_close_price,
      limit_close_offset
    ) VALUES (
      new_id,
      'High Water Test 1',
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
      0.0000,
      false,
      false,
      0.0000,
      0.0100
    );
    PERFORM setval(
      pg_get_serial_sequence('system.strategy_list_default', 'id'),
      (SELECT MAX(id) FROM system.strategy_list_default)
    );
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
        AND column_name = 'verification_period_enabled'
    ) THEN
      UPDATE system.strategy_list_default
      SET verification_period_enabled = TRUE, verification_period_seconds = 3
      WHERE name = 'High Water Test 1';
    END IF;
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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_price'
      ) INTO has_lcp;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) INTO has_lco;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'time_in_force'
      ) INTO has_tif;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'order_type'
      ) INTO has_ot;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'verification_period_enabled'
      ) INTO has_verify_en;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'verification_period_seconds'
      ) INTO has_verify_sec;

      IF has_default_col AND has_lcp AND has_lco THEN
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name, "default",
            min_time, max_time, min_probability, max_probability,
            min_ask, max_ask, min_volume, min_differential,
            spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
            performance_based_allocation, limit_close_price, limit_close_offset
          )
          SELECT
            'High Water Test 1', false,
            0, 60, 90, 100,
            0.9000, 0.9900, 0, 0.00,
            false, 0.0000, false,
            false, 0.0000, 0.0100
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'High Water Test 1'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      ELSIF has_lcp AND has_lco THEN
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name,
            min_time, max_time, min_probability, max_probability,
            min_ask, max_ask, min_volume, min_differential,
            spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
            performance_based_allocation, limit_close_price, limit_close_offset
          )
          SELECT
            'High Water Test 1',
            0, 60, 90, 100,
            0.9000, 0.9900, 0, 0.00,
            false, 0.0000, false,
            false, 0.0000, 0.0100
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'High Water Test 1'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      END IF;

      IF has_verify_en AND has_verify_sec THEN
        EXECUTE format(
          'UPDATE %I.%I SET verification_period_enabled = TRUE, verification_period_seconds = 3
           WHERE name = %L',
          sch, tbl, 'High Water Test 1'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
