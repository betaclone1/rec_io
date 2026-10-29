-- Correct MTB membership for non-trading cash wallets.
-- Seed in 20261027_0630 keyed off id=0; some tenants label CASH/PRIMARY on other ids.

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
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'in_mtb'
      ) THEN
        EXECUTE format(
          'UPDATE %I.%I SET in_mtb = FALSE
           WHERE id = 0
              OR upper(subaccount) IN (''CASH'', ''PRIMARY'')',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
