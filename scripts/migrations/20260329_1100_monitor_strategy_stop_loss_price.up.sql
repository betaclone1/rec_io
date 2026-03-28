-- Per-monitor / per-strategy ask-gate stop floor (0 = disabled). NUMERIC(6,4), max 0.9900 enforced in API.

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
        AND column_name = 'stop_loss_price'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN stop_loss_price NUMERIC(6,4) DEFAULT 0.0000',
        tbl
      );
      EXECUTE format(
        'UPDATE users.%I SET stop_loss_price = 0.0000 WHERE stop_loss_price IS NULL',
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
        AND column_name = 'stop_loss_price'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN stop_loss_price NUMERIC(6,4) DEFAULT 0.0000',
        tbl
      );
      EXECUTE format(
        'UPDATE users.%I SET stop_loss_price = 0.0000 WHERE stop_loss_price IS NULL',
        tbl
      );
    END IF;
  END LOOP;
END
$$;
