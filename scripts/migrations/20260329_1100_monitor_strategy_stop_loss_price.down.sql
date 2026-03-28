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
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS stop_loss_price', tbl);
  END LOOP;

  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'strategy_list_%'
  LOOP
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS stop_loss_price', tbl);
  END LOOP;
END
$$;
