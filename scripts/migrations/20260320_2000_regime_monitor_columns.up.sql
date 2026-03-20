-- Regime Monitor settings (LIVE <-> PAPER auto-switch)
-- Adds:
--   - users.monitor_list_*/regime_monitor_enabled (feature toggle)
--   - users.monitor_list_*/regime_window (lookback window selector)

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
    -- regime_monitor_enabled
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'regime_monitor_enabled'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE',
        tbl
      );
      EXECUTE format(
        'UPDATE users.%I SET regime_monitor_enabled = FALSE WHERE regime_monitor_enabled IS NULL',
        tbl
      );
    END IF;

    -- regime_window
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'regime_window'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN regime_window TEXT DEFAULT %L',
        tbl,
        '30d'
      );
      EXECUTE format(
        'UPDATE users.%I SET regime_window = %L WHERE regime_window IS NULL',
        tbl,
        '30d'
      );
    END IF;
  END LOOP;
END
$$;

