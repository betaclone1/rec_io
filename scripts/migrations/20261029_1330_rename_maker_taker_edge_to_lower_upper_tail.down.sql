-- Revert product strategy labels: Lower Tail → Maker Edge, Upper Tail → Taker Edge.

DO $$
DECLARE
  sch text;
  tbl text;
  has_col boolean;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    UPDATE system.strategy_list_default SET name = 'Maker Edge' WHERE name = 'Lower Tail';
    UPDATE system.strategy_list_default SET name = 'Taker Edge' WHERE name = 'Upper Tail';
  END IF;

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
      EXECUTE format(
        'UPDATE %I.%I SET name = %L WHERE name = %L',
        sch, tbl, 'Maker Edge', 'Lower Tail'
      );
      EXECUTE format(
        'UPDATE %I.%I SET name = %L WHERE name = %L',
        sch, tbl, 'Taker Edge', 'Upper Tail'
      );
    END LOOP;

    FOR tbl IN
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = sch AND table_name LIKE 'monitor_list_%'
      ORDER BY 1
    LOOP
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'strategy'
      ) INTO has_col;
      IF has_col THEN
        EXECUTE format(
          'UPDATE %I.%I SET strategy = %L WHERE strategy = %L',
          sch, tbl, 'Maker Edge', 'Lower Tail'
        );
        EXECUTE format(
          'UPDATE %I.%I SET strategy = %L WHERE strategy = %L',
          sch, tbl, 'Taker Edge', 'Upper Tail'
        );
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = sch AND table_name LIKE 'trades_%'
      ORDER BY 1
    LOOP
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'trade_strategy'
      ) INTO has_col;
      IF has_col THEN
        EXECUTE format(
          'UPDATE %I.%I SET trade_strategy = %L WHERE trade_strategy = %L',
          sch, tbl, 'Maker Edge', 'Lower Tail'
        );
        EXECUTE format(
          'UPDATE %I.%I SET trade_strategy = %L WHERE trade_strategy = %L',
          sch, tbl, 'Taker Edge', 'Upper Tail'
        );
      END IF;

      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'entry_method'
      ) INTO has_col;
      IF has_col THEN
        EXECUTE format(
          'UPDATE %I.%I SET entry_method = %L WHERE entry_method = %L',
          sch, tbl, 'maker_edge', 'lower_tail'
        );
        EXECUTE format(
          'UPDATE %I.%I SET entry_method = %L WHERE entry_method = %L',
          sch, tbl, 'taker_edge', 'upper_tail'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
