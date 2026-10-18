-- Per-subaccount drawdown halt controls (parity with system_settings drawdown columns).
-- Live + paper subaccounts_* under users and users_NNNN.
-- Seed from matching system_settings when present; else defaults TRUE / 50.00.

DO $$
DECLARE
  sch text;
  tbl text;
  settings_tbl text;
  slot text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^subaccounts(_paper)?_[0-9]{4}$'
      ORDER BY 1
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'drawdown_trading_halt'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN drawdown_trading_halt BOOLEAN NOT NULL DEFAULT TRUE',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'drawdown_reset_threshold_pct'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN drawdown_reset_threshold_pct NUMERIC(5,2) NOT NULL DEFAULT 50.00 '
          'CHECK (drawdown_reset_threshold_pct > 0 AND drawdown_reset_threshold_pct < 100)',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'trading_halt_active'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN trading_halt_active BOOLEAN NOT NULL DEFAULT FALSE',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'drawdown_halt_monitor_snapshot'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN drawdown_halt_monitor_snapshot JSONB',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.drawdown_trading_halt IS %L',
        sch, tbl,
        'When true, apply sticky bankroll drawdown step-down + emergency halt for monitors on this subaccount.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.drawdown_reset_threshold_pct IS %L',
        sch, tbl,
        'Percent drawdown from this subaccount sticky bankroll_current that triggers step-down (exclusive 0–100).'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.trading_halt_active IS %L',
        sch, tbl,
        'Latch set true when drawdown emergency halt is applied for monitors on this subaccount.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.drawdown_halt_monitor_snapshot IS %L',
        sch, tbl,
        'Pre-halt paper_trade/test_filter snapshot for monitors on this subaccount (schema_version 1).'
      );

      -- Seed from tenant system_settings when available
      slot := substring(tbl from '([0-9]{4})$');
      IF slot IS NOT NULL THEN
        settings_tbl := 'system_settings_' || slot;
        IF EXISTS (
          SELECT 1 FROM information_schema.tables t
          WHERE t.table_schema = sch AND t.table_name = settings_tbl
        ) THEN
          EXECUTE format(
            'UPDATE %I.%I sa SET '
            'drawdown_trading_halt = COALESCE(ss.drawdown_trading_halt, sa.drawdown_trading_halt), '
            'drawdown_reset_threshold_pct = COALESCE(ss.drawdown_reset_threshold_pct, sa.drawdown_reset_threshold_pct) '
            'FROM %I.%I ss WHERE ss.id = 1',
            sch, tbl, sch, settings_tbl
          );
        END IF;
      END IF;
    END LOOP;
  END LOOP;
END
$$;
