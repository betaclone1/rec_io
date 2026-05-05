-- Drop performance rollup tables and NOTIFY triggers (per trades_<slot> in each tenant schema).

DO $$
DECLARE
  sch text;
  trade_tbl text;
  slot text;
  tot text;
  mon text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR trade_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^trades_[0-9]{4}$'
    LOOP
      slot := (regexp_match(trade_tbl, 'trades_([0-9]{4})$'))[1];
      IF slot IS NULL THEN
        CONTINUE;
      END IF;
      tot := 'performance_total_' || slot;
      mon := 'performance_monitors_' || slot;

      IF to_regclass(format('%I.%I', sch, tot)) IS NOT NULL THEN
        EXECUTE format(
          'DROP TRIGGER IF EXISTS %I ON %I.%I',
          tot || '_rec_io_db_notify', sch, tot
        );
        EXECUTE format('DROP TABLE IF EXISTS %I.%I CASCADE', sch, tot);
      END IF;

      IF to_regclass(format('%I.%I', sch, mon)) IS NOT NULL THEN
        EXECUTE format(
          'DROP TRIGGER IF EXISTS %I ON %I.%I',
          mon || '_rec_io_db_notify', sch, mon
        );
        EXECUTE format('DROP TABLE IF EXISTS %I.%I CASCADE', sch, mon);
      END IF;
    END LOOP;
  END LOOP;
END
$$;
