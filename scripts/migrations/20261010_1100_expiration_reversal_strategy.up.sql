-- Expiration Reversal strategy.
-- 1) Seed "Expiration Reversal" in system.strategy_list_default and every tenant strategy_list_*
--    as a copy of that table's own "Expiration Scalp" row, with flip_sell_floor = TRUE
--    (flip_sell_floor_mult keeps the copied value, '1x' when unset). Tables without an
--    "Expiration Scalp" row get no ER row.
-- 2) CHECK on monitor_list_* / strategy_list_* (users + users_NNNN + system default):
--    strategy/name 'Expiration Reversal' requires flip_sell_floor IS TRUE.

DO $$
DECLARE
  sch text;
  tbl text;
  cols text;
  new_id integer;
  seq text;
  has_default_col boolean;
  should_seed boolean;
BEGIN
  FOR sch, tbl IN
    SELECT 'system'::text, 'strategy_list_default'::text
    WHERE to_regclass('system.strategy_list_default') IS NOT NULL
    UNION ALL
    SELECT t.table_schema::text, t.table_name::text
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name LIKE 'strategy_list_%'
      AND t.table_type = 'BASE TABLE'
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_floor'
    ) THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE name = %L) AND NOT EXISTS (SELECT 1 FROM %I.%I WHERE name = %L)',
      sch, tbl, 'Expiration Scalp', sch, tbl, 'Expiration Reversal'
    ) INTO should_seed;
    IF NOT should_seed THEN
      CONTINUE;
    END IF;

    SELECT string_agg(quote_ident(c.column_name), ', ' ORDER BY c.ordinal_position)
    INTO cols
    FROM information_schema.columns c
    WHERE c.table_schema = sch AND c.table_name = tbl
      AND c.column_name NOT IN (
        'id', 'name', 'default', 'created', 'updated',
        'flip_sell_floor', 'flip_sell_floor_mult'
      );

    SELECT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'default'
    ) INTO has_default_col;

    EXECUTE format('SELECT COALESCE(MAX(id), 0) + 1 FROM %I.%I', sch, tbl) INTO new_id;

    EXECUTE format(
      'INSERT INTO %I.%I (id, name, %s flip_sell_floor, flip_sell_floor_mult, %s)
       SELECT %s, %L, %s TRUE, COALESCE(NULLIF(BTRIM(flip_sell_floor_mult), ''''), %L), %s
       FROM %I.%I WHERE name = %L',
      sch, tbl,
      CASE WHEN has_default_col THEN '"default",' ELSE '' END,
      cols,
      new_id, 'Expiration Reversal',
      CASE WHEN has_default_col THEN 'FALSE,' ELSE '' END,
      '1x',
      cols,
      sch, tbl, 'Expiration Scalp'
    );

    seq := pg_get_serial_sequence(format('%I.%I', sch, tbl), 'id');
    IF seq IS NOT NULL AND sch <> 'system' THEN
      EXECUTE format(
        'SELECT setval(%L, GREATEST((SELECT MAX(id) FROM %I.%I), (SELECT last_value FROM %s)), true)',
        seq, sch, tbl, seq
      );
    END IF;
  END LOOP;

  FOR sch, tbl IN
    SELECT 'system'::text, 'strategy_list_default'::text
    WHERE to_regclass('system.strategy_list_default') IS NOT NULL
    UNION ALL
    SELECT t.table_schema::text, t.table_name::text
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND (t.table_name LIKE 'strategy_list_%' OR t.table_name LIKE 'monitor_list_%')
      AND t.table_type = 'BASE TABLE'
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_floor'
    ) THEN
      CONTINUE;
    END IF;
    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = format('%I.%I', sch, tbl)::regclass
        AND conname = 'expiration_reversal_flip_floor_chk'
    ) THEN
      CONTINUE;
    END IF;
    IF tbl LIKE 'monitor_list_%' THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD CONSTRAINT expiration_reversal_flip_floor_chk
         CHECK (strategy IS DISTINCT FROM %L OR flip_sell_floor IS TRUE)',
        sch, tbl, 'Expiration Reversal'
      );
    ELSE
      EXECUTE format(
        'ALTER TABLE %I.%I ADD CONSTRAINT expiration_reversal_flip_floor_chk
         CHECK (name IS DISTINCT FROM %L OR flip_sell_floor IS TRUE)',
        sch, tbl, 'Expiration Reversal'
      );
    END IF;
  END LOOP;
END $$;
