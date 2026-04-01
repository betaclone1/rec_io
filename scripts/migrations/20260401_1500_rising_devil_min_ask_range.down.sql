DELETE FROM users.strategy_list_0001 WHERE name = 'Rising Devil';

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'monitor_list_%'
  LOOP
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS min_ask_range', tbl);
  END LOOP;

  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'strategy_list_%'
  LOOP
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS min_ask_range', tbl);
  END LOOP;
END
$$;
