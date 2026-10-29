-- VER4 first-move capital shape:
--   subaccounts_*: in_mtb (MTB membership), mtb_weight_pct (% of portfolio MTB Base)
--   system_settings_*: mtb_base_value_cents (portfolio MTB Base Value)
-- Seed: CASH (#0) in_mtb=false; all other existing subaccount rows in_mtb=true.
-- Weights stay NULL until the operator sets them (Unallocated residual).

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
        AND t.table_name ~ '^subaccounts(_paper)?_[0-9]{4}$'
      ORDER BY 1
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'in_mtb'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN in_mtb BOOLEAN NOT NULL DEFAULT FALSE',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'mtb_weight_pct'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN mtb_weight_pct DOUBLE PRECISION NULL '
          'CHECK (mtb_weight_pct IS NULL OR (mtb_weight_pct >= 0 AND mtb_weight_pct <= 100))',
          sch, tbl
        );
      END IF;

      -- Existing non-cash rows join the trading/MTB set; CASH/PRIMARY stay outside.
      EXECUTE format(
        'UPDATE %I.%I SET in_mtb = TRUE
         WHERE in_mtb = FALSE
           AND id <> 0
           AND upper(subaccount) NOT IN (''CASH'', ''PRIMARY'')',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET in_mtb = FALSE
         WHERE id = 0 OR upper(subaccount) IN (''CASH'', ''PRIMARY'')',
        sch, tbl
      );

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.in_mtb IS %L',
        sch, tbl,
        'TRUE = counts toward live MTB (trading-set capital). CASH (#0) is FALSE.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.mtb_weight_pct IS %L',
        sch, tbl,
        'Percent of portfolio MTB Base Value (0-100). NULL = unweighted / residual Unallocated inside MTB.'
      );
    END LOOP;

    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^system_settings_[0-9]{4}$'
      ORDER BY 1
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'mtb_base_value_cents'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN mtb_base_value_cents INTEGER NULL '
          'CHECK (mtb_base_value_cents IS NULL OR mtb_base_value_cents >= 0)',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.mtb_base_value_cents IS %L',
        sch, tbl,
        'Portfolio MTB Base Value in cents. Policy SA targets = mtb_weight_pct %% of this. Distinct from per-SA base_value (rake).'
      );
    END LOOP;
  END LOOP;
END
$$;
