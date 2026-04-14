-- Ensure every users_NNNN silo has the same timestamp behavior as 0001:
-- 1) account_balance / account_balance_paper: backfill NULL created_at/updated_at from "timestamp" text;
--    set DEFAULT CURRENT_TIMESTAMP so plain INSERTs without those columns still populate them.
-- 2) trades / trades_simulated: backfill NULL created_at/updated_at from "date" + "time" (US/Eastern wall);
--    set DEFAULT CURRENT_TIMESTAMP on both columns.

DO $$
DECLARE
  ns text;
  rel text;
BEGIN
  FOR ns IN
    SELECT nspname FROM pg_namespace WHERE nspname ~ '^users_[0-9]{4}$'
  LOOP
    FOR rel IN
      SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = ns
        AND c.relkind = 'r'
        AND c.relname ~ '^(account_balance|account_balance_paper)_[0-9]{4}$'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = ns AND table_name = rel AND column_name = 'created_at'
      ) THEN
        EXECUTE format(
          'UPDATE %I.%I SET '
          || 'created_at = COALESCE(created_at, (NULLIF(BTRIM("timestamp"), '''')::timestamptz)), '
          || 'updated_at = COALESCE(updated_at, (NULLIF(BTRIM("timestamp"), '''')::timestamptz)) '
          || 'WHERE created_at IS NULL OR updated_at IS NULL',
          ns, rel
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP',
          ns, rel
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP',
          ns, rel
        );
      END IF;
    END LOOP;

    FOR rel IN
      SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = ns
        AND c.relkind = 'r'
        AND c.relname ~ '^(trades|trades_simulated)_[0-9]{4}$'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = ns AND table_name = rel AND column_name = 'created_at'
      ) THEN
        EXECUTE format(
          'UPDATE %I.%I SET '
          || 'created_at = COALESCE(created_at, '
          || 'CASE WHEN "date" IS NOT NULL AND BTRIM("date") ~ ''^[0-9]{4}-[0-9]{2}-[0-9]{2}$'' '
          || 'AND "time" IS NOT NULL AND BTRIM("time") <> '''' '
          || 'THEN ((BTRIM("date") || '' '' || BTRIM("time"))::timestamp AT TIME ZONE ''America/New_York'') '
          || 'ELSE NULL END), '
          || 'updated_at = COALESCE(updated_at, created_at, '
          || 'CASE WHEN "date" IS NOT NULL AND BTRIM("date") ~ ''^[0-9]{4}-[0-9]{2}-[0-9]{2}$'' '
          || 'AND "time" IS NOT NULL AND BTRIM("time") <> '''' '
          || 'THEN ((BTRIM("date") || '' '' || BTRIM("time"))::timestamp AT TIME ZONE ''America/New_York'') '
          || 'ELSE NULL END) '
          || 'WHERE created_at IS NULL OR updated_at IS NULL',
          ns, rel
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP',
          ns, rel
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP',
          ns, rel
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
