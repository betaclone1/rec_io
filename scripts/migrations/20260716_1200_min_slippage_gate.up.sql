-- Auto-entry min_slippage gate.
--   monitor_list_*: per-monitor projected-slippage floor (0.0000 = gate disabled, range -0.1000..0.0000).
--   trades_* / trades_simulated_*: snapshot the monitor min_slippage on each row at insert.
-- Applied to every tenant schema (users + users_NNNN) for parity.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    -- monitor_list_*: nullable, defaulted to 0.0000 (disabled)
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_slippage'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN min_slippage NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.min_slippage IS %L',
        sch, tbl,
        'Minimum acceptable projected entry slippage (estimated fill minus trigger price, dollars). 0.0000 disables; enabled range -0.1000..0.0000. TM rejects opens whose projected slippage is below this.'
      );
    END LOOP;

    -- trades_* / trades_simulated_*: NOT NULL snapshot of monitor min_slippage at insert
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_slippage'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN min_slippage NUMERIC(6,4) NOT NULL DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
