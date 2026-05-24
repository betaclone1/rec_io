-- Subaccount-native balance polling: rename CASH/undefined_2 labels; per-subaccount balance history tables.
-- Loops legacy users + tenant users_NNNN schemas (parity).

DO $$
DECLARE
  sch text;
  tbl text;
  slot text;
  ab_tbl text;
  sab_tbl text;
  n int;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    -- Rename subaccount labels (live + paper)
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^subaccounts(_paper)?_[0-9]{4}$'
    LOOP
      EXECUTE format(
        'UPDATE %I.%I SET subaccount = %L WHERE subaccount = %L',
        sch, tbl, 'CASH', 'PRIMARY'
      );
      EXECUTE format(
        'UPDATE %I.%I SET subaccount = %L WHERE subaccount = %L',
        sch, tbl, 'undefined_2', 'Cash Transfer'
      );
    END LOOP;

    -- Per-subaccount balance history (0, 1, 2) LIKE account_balance_<slot>
    FOR ab_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^account_balance_[0-9]{4}$'
    LOOP
      slot := substring(ab_tbl from '([0-9]{4})$');
      FOREACH n IN ARRAY ARRAY[0, 1, 2]
      LOOP
        sab_tbl := format('subaccount_balance_%s_%s', slot, n);
        IF NOT EXISTS (
          SELECT 1
          FROM information_schema.tables t2
          WHERE t2.table_schema = sch AND t2.table_name = sab_tbl
        ) THEN
          EXECUTE format(
            'CREATE TABLE %I.%I (LIKE %I.%I INCLUDING ALL)',
            sch, sab_tbl, sch, ab_tbl
          );
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END
$$;
