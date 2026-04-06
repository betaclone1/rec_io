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
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS flip_sell_floor_mult', tbl);
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS flip_sell_prob_mult', tbl);
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS flip_sell_floor', tbl);
    EXECUTE format('ALTER TABLE users.%I DROP COLUMN IF EXISTS flip_sell_prob', tbl);
  END LOOP;
END
$$;
