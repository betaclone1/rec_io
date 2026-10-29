-- Rename product strategy labels: Maker Edge → Lower Tail, Taker Edge → Upper Tail.
-- Updates strategy_list names, monitor strategy refs, and trade strategy/entry_method
-- across system + every tenant schema. Historical seed migration ids stay unchanged.

DO $$
DECLARE
  sch text;
  tbl text;
  has_col boolean;
BEGIN
  -- system.strategy_list_default
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    UPDATE system.strategy_list_default SET name = 'Lower Tail' WHERE name = 'Maker Edge';
    UPDATE system.strategy_list_default SET name = 'Upper Tail' WHERE name = 'Taker Edge';
  END IF;

  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    -- strategy_list_*
    FOR tbl IN
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = sch AND table_name LIKE 'strategy_list_%'
      ORDER BY 1
    LOOP
      EXECUTE format(
        'UPDATE %I.%I SET name = %L WHERE name = %L',
        sch, tbl, 'Lower Tail', 'Maker Edge'
      );
      EXECUTE format(
        'UPDATE %I.%I SET name = %L WHERE name = %L',
        sch, tbl, 'Upper Tail', 'Taker Edge'
      );
    END LOOP;

    -- monitor_list_*.strategy
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
          sch, tbl, 'Lower Tail', 'Maker Edge'
        );
        EXECUTE format(
          'UPDATE %I.%I SET strategy = %L WHERE strategy = %L',
          sch, tbl, 'Upper Tail', 'Taker Edge'
        );
      END IF;
    END LOOP;

    -- trades_*: trade_strategy + entry_method
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
          sch, tbl, 'Lower Tail', 'Maker Edge'
        );
        EXECUTE format(
          'UPDATE %I.%I SET trade_strategy = %L WHERE trade_strategy = %L',
          sch, tbl, 'Upper Tail', 'Taker Edge'
        );
      END IF;

      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'entry_method'
      ) INTO has_col;
      IF has_col THEN
        EXECUTE format(
          'UPDATE %I.%I SET entry_method = %L WHERE entry_method = %L',
          sch, tbl, 'lower_tail', 'maker_edge'
        );
        EXECUTE format(
          'UPDATE %I.%I SET entry_method = %L WHERE entry_method = %L',
          sch, tbl, 'upper_tail', 'taker_edge'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
