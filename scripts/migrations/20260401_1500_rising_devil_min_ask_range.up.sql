-- Rising Devil: min ask range threshold (dollar units, same scale as yes_ask_range_15m). NULL = unset.

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
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'min_ask_range'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN min_ask_range NUMERIC(18,4)',
        tbl
      );
    END IF;
  END LOOP;

  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'strategy_list_%'
  LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'min_ask_range'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN min_ask_range NUMERIC(18,4)',
        tbl
      );
    END IF;
  END LOOP;
END
$$;

INSERT INTO users.strategy_list_0001 (name, min_ask_range)
SELECT 'Rising Devil', 0.7000
WHERE NOT EXISTS (
  SELECT 1 FROM users.strategy_list_0001 WHERE name = 'Rising Devil'
);
