-- Reverse win_streak_one_contract -> one_contract on monitor/strategy rows; drop trades.loss_prevention_state.

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_name ~ '^monitor_list_[0-9]{4}$'
      AND table_schema ~ '^(users|users_[0-9]{4})$'
  LOOP
    EXECUTE format(
      'UPDATE %I.%I SET loss_prevention = %L WHERE loss_prevention IS NOT NULL AND lower(trim(loss_prevention::text)) = %L',
      r.table_schema,
      r.table_name,
      'one_contract',
      'win_streak_one_contract'
    );
  END LOOP;

  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_name ~ '^strategy_list_[0-9]{4}$'
      AND table_schema ~ '^(users|users_[0-9]{4})$'
  LOOP
    EXECUTE format(
      'UPDATE %I.%I SET loss_prevention = %L WHERE loss_prevention IS NOT NULL AND lower(trim(loss_prevention::text)) = %L',
      r.table_schema,
      r.table_name,
      'one_contract',
      'win_streak_one_contract'
    );
  END LOOP;

  IF to_regclass('system.strategy_list_default') IS NOT NULL THEN
    UPDATE system.strategy_list_default
    SET loss_prevention = 'one_contract'
    WHERE loss_prevention IS NOT NULL
      AND lower(trim(loss_prevention::text)) = 'win_streak_one_contract';
  END IF;
END $$;

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_name ~ '^trades_[0-9]{4}$'
      AND table_schema ~ '^(users|users_[0-9]{4})$'
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = r.table_schema
        AND c.table_name = r.table_name
        AND c.column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN loss_prevention_state',
        r.table_schema,
        r.table_name
      );
    END IF;
  END LOOP;
END $$;
