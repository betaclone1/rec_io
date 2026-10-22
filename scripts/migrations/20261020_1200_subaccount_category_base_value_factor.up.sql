-- Subaccount category and base-value policy inputs.
-- Live + paper subaccounts_* under users and users_NNNN.
-- Defaults: category crypto, base_value_format percent, base_value_factor 100.
-- Existing base_value (cents) is unchanged; consumers of format/factor come later.

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
          AND c.column_name = 'category'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN category TEXT NOT NULL DEFAULT ''crypto'' '
          'CHECK (category IN (''crypto'', ''commodity''))',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'base_value_format'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN base_value_format TEXT NOT NULL DEFAULT ''percent'' '
          'CHECK (base_value_format IN (''percent'', ''amount''))',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'base_value_factor'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN base_value_factor DOUBLE PRECISION NOT NULL DEFAULT 100',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.category IS %L',
        sch, tbl,
        'Market category for this subaccount. Allowed: crypto, commodity.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.base_value_format IS %L',
        sch, tbl,
        'How base_value_factor is interpreted: percent of subaccount balance, or amount in dollars.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.base_value_factor IS %L',
        sch, tbl,
        'Factor for base_value_format. percent: 100 = 100%% of balance. amount: hard dollars (cents = round(factor * 100) when wired).'
      );
    END LOOP;
  END LOOP;
END
$$;
