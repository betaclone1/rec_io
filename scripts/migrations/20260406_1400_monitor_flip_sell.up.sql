-- Flip Sell: probability-stop and floor-stop toggles and multiplier strings (e.g. 1x, future max).
-- Booleans default FALSE; mults NULL until first enable (app sets 1x) or user sets explicitly.
-- Schemas: legacy `users` and tenant `users_NNNN` (runner may rewrite `users.` in COMMENT strings;
-- DDL uses %I schema so both shapes work).

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
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_prob'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_floor'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_prob_mult'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN flip_sell_prob_mult VARCHAR(32)',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_floor_mult'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN flip_sell_floor_mult VARCHAR(32)',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.flip_sell_prob IS %L',
        sch, tbl,
        'When true, allow flip-sell sizing for probability-based auto stops.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.flip_sell_floor IS %L',
        sch, tbl,
        'When true, allow flip-sell sizing for floor-price stops.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.flip_sell_prob_mult IS %L',
        sch, tbl,
        'Flip-sell size token for prob stops (e.g. 1x); NULL until enabled or set.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.flip_sell_floor_mult IS %L',
        sch, tbl,
        'Flip-sell size token for floor stops (e.g. 1x); NULL until enabled or set.'
      );
    END LOOP;
  END LOOP;
END
$$;
