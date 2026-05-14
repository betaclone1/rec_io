-- Rename Kalshi direction column side -> outcome_side on all tenant orders_/fills_ tables;
-- add orderbook_side (backfill yes->bid, no->ask). Create credits_history_<slot> per orders_<slot>.
-- Schemas: legacy users + users_NNNN (tenant parity).

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^(orders|fills)_[0-9]{4}$'
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = r.table_schema
        AND c.table_name = r.table_name
        AND c.column_name = 'outcome_side'
    ) THEN
      CONTINUE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = r.table_schema
        AND c.table_name = r.table_name
        AND c.column_name = 'side'
    ) THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS orderbook_side TEXT',
      r.table_schema,
      r.table_name
    );

    EXECUTE format(
      $u$
      UPDATE %I.%I
      SET orderbook_side = CASE lower(trim(side::text))
        WHEN 'yes' THEN 'bid'
        WHEN 'no' THEN 'ask'
        ELSE NULL
      END
      WHERE orderbook_side IS NULL AND side IS NOT NULL
      $u$,
      r.table_schema,
      r.table_name
    );

    EXECUTE format(
      'ALTER TABLE %I.%I RENAME COLUMN side TO outcome_side',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;

DO $$
DECLARE
  r RECORD;
  cred_name TEXT;
BEGIN
  FOR r IN
    SELECT DISTINCT
      t.table_schema AS sch,
      (substring(t.table_name from 'orders_(.*)$'))::text AS slot
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^orders_[0-9]{4}$'
  LOOP
    IF r.slot IS NULL OR length(trim(r.slot)) = 0 THEN
      CONTINUE;
    END IF;
    cred_name := format('credits_history_%s', r.slot);
    IF EXISTS (
      SELECT 1
      FROM information_schema.tables x
      WHERE x.table_schema = r.sch
        AND x.table_name = cred_name
    ) THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      $c$
      CREATE TABLE %I.%I (
        credit_id TEXT PRIMARY KEY,
        status TEXT,
        type TEXT,
        amount_cents INTEGER,
        reason TEXT,
        created_at TIMESTAMPTZ,
        raw_json TEXT,
        synced_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
      )
      $c$,
      r.sch,
      cred_name
    );

    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I (created_at DESC)',
      format('idx_%s_created', replace(cred_name, '.', '_')),
      r.sch,
      cred_name
    );
  END LOOP;
END $$;
