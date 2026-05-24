-- Revert subaccount balance polling migration (labels + per-subaccount balance tables).

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
        IF EXISTS (
          SELECT 1
          FROM information_schema.tables t2
          WHERE t2.table_schema = sch AND t2.table_name = sab_tbl
        ) THEN
          EXECUTE format('DROP TABLE IF EXISTS %I.%I', sch, sab_tbl);
        END IF;
      END LOOP;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^subaccounts(_paper)?_[0-9]{4}$'
    LOOP
      EXECUTE format(
        'UPDATE %I.%I SET subaccount = %L WHERE subaccount = %L',
        sch, tbl, 'PRIMARY', 'CASH'
      );
      EXECUTE format(
        'UPDATE %I.%I SET subaccount = %L WHERE subaccount = %L',
        sch, tbl, 'Cash Transfer', 'undefined_2'
      );
    END LOOP;
  END LOOP;
END
$$;
