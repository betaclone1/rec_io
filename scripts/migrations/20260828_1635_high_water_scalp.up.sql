-- High Water Scalp: limit_close_price (monitor/strategy/trade snapshot) + close_filled_count
-- on trades, plus strategy_list seed. Owned-side dollars (e.g. 0.99), not opposite-leg 0.01.

DO $$
DECLARE
  sch text;
  tbl text;
  new_id integer;
  has_default_col boolean;
  has_lcp boolean;
  has_tif boolean;
  has_ot boolean;
  has_verify_en boolean;
  has_verify_sec boolean;
BEGIN
  -- monitor_list_*
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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN limit_close_price NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.limit_close_price IS %L',
        sch, tbl,
        'High Water Scalp: owned-side GTC close target dollars (e.g. 0.99). 0 disables. Migration 20260828_1635_high_water_scalp.'
      );
    END LOOP;

    -- strategy_list_*
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN limit_close_price NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;

    -- trades_* / trades_simulated_*
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN limit_close_price NUMERIC(6,4) NOT NULL DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'close_filled_count'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN close_filled_count NUMERIC(12,2) NOT NULL DEFAULT 0.00',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  -- system.strategy_list_default
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'limit_close_price'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN limit_close_price NUMERIC(6,4) DEFAULT 0.0000;
    END IF;
  END IF;

  -- archive trades UNION parity (nullable: historical rows have no snapshot)
  FOR tbl IN
    SELECT t.table_name FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS limit_close_price NUMERIC(6,4)',
      tbl
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS close_filled_count NUMERIC(12,2)',
      tbl
    );
  END LOOP;

  -- Seed High Water Scalp on system.strategy_list_default
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) AND NOT EXISTS (
    SELECT 1 FROM system.strategy_list_default WHERE name = 'High Water Scalp'
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
      limit_close_price
    ) VALUES (
      new_id,
      'High Water Scalp',
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
      0.9900
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
      WHERE name = 'High Water Scalp';
    END IF;
  ELSE
    UPDATE system.strategy_list_default
    SET limit_close_price = 0.9900
    WHERE name = 'High Water Scalp' AND (limit_close_price IS NULL OR limit_close_price = 0);
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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_price'
      ) INTO has_lcp;
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

      IF has_default_col AND has_lcp THEN
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name, "default",
            min_time, max_time, min_probability, max_probability,
            min_ask, max_ask, min_volume, min_differential,
            spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
            performance_based_allocation, limit_close_price
          )
          SELECT
            'High Water Scalp', false,
            0, 60, 90, 100,
            0.9000, 0.9900, 0, 0.00,
            false, 0.0000, false,
            false, 0.9900
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'High Water Scalp'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      ELSIF has_lcp THEN
        EXECUTE format(
          $sql$
          INSERT INTO %I.%I (
            name,
            min_time, max_time, min_probability, max_probability,
            min_ask, max_ask, min_volume, min_differential,
            spike_alert_enabled, stop_loss_price, loss_prevention_toggle,
            performance_based_allocation, limit_close_price
          )
          SELECT
            'High Water Scalp',
            0, 60, 90, 100,
            0.9000, 0.9900, 0, 0.00,
            false, 0.0000, false,
            false, 0.9900
          WHERE NOT EXISTS (
            SELECT 1 FROM %I.%I WHERE name = 'High Water Scalp'
          )
          $sql$,
          sch, tbl, sch, tbl
        );
      END IF;

      IF has_verify_en AND has_verify_sec THEN
        EXECUTE format(
          'UPDATE %I.%I SET verification_period_enabled = TRUE, verification_period_seconds = 3
           WHERE name = %L',
          sch, tbl, 'High Water Scalp'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
