-- Add projected entry fields for orderbook-based pre-trade estimates.
-- Applies to legacy users schema and all tenant users_NNNN schemas.
DO $$
DECLARE
  sch text;
  tbl text;
  sim_tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    tbl := replace('trades_0001', '0001', right(sch, 4));
    sim_tbl := replace('trades_simulated_0001', '0001', right(sch, 4));
    IF sch = 'users' THEN
      tbl := 'trades_0001';
      sim_tbl := 'trades_simulated_0001';
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema = sch
        AND table_name = tbl
    ) THEN
      IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = sch
          AND table_name = tbl
          AND column_name = 'initial_proj_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN initial_proj_price NUMERIC(10,8)',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = sch
          AND table_name = tbl
          AND column_name = 'initial_proj_fees'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN initial_proj_fees NUMERIC(10,4)',
          sch, tbl
        );
      END IF;
    END IF;

    -- Keep trades_simulated shape aligned with trades table.
    IF EXISTS (
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema = sch
        AND table_name = sim_tbl
    ) THEN
      IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = sch
          AND table_name = sim_tbl
          AND column_name = 'initial_proj_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN initial_proj_price NUMERIC(10,8)',
          sch, sim_tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = sch
          AND table_name = sim_tbl
          AND column_name = 'initial_proj_fees'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN initial_proj_fees NUMERIC(10,4)',
          sch, sim_tbl
        );
      END IF;
    END IF;
  END LOOP;
END
$$;
