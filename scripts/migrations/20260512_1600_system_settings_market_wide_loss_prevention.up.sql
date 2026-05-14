-- Market-wide loss prevention: per-user system_settings hero monitor + threshold + master toggle.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch, tbl IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name ~ '^system_settings_'
    ORDER BY 1, 2
  LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'market_wide_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN market_wide_loss_prevention BOOLEAN NOT NULL DEFAULT TRUE',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'hero_monitor_id'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN hero_monitor_id INTEGER',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'stop_loss_count_threshold'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN stop_loss_count_threshold INTEGER',
        sch, tbl
      );
    END IF;

    EXECUTE format(
      'COMMENT ON COLUMN %I.%I.market_wide_loss_prevention IS %L',
      sch, tbl,
      'When true, symbol_wide_loss_prevention monitors may follow global hero loss-count gate (live_loss_market_wide_1c).'
    );
    EXECUTE format(
      'COMMENT ON COLUMN %I.%I.hero_monitor_id IS %L',
      sch, tbl,
      'monitor_list id for global volatility hero (e.g. BTC hourly HTC); NULL disables market-wide gate.'
    );
    EXECUTE format(
      'COMMENT ON COLUMN %I.%I.stop_loss_count_threshold IS %L',
      sch, tbl,
      'Hero loss_prevention_cooldown_loss_count must be >= this to trigger market-wide 1c; NULL disables gate.'
    );
  END LOOP;
END $$;
