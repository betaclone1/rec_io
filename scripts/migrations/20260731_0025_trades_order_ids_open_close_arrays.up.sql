-- Multi-leg open/close order membership on trades.
-- Scalar order_id_open / order_id_close remain the active confirm pointers.
-- order_ids_* hold append-only filled-leg membership (never wiped by zero-fill top-ups).

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  -- Tenant trades / trades_simulated
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
        AND t.table_type = 'BASE TABLE'
        AND (
          t.table_name ~ '^trades_[0-9]{4}$'
          OR t.table_name ~ '^trades_simulated_[0-9]{4}$'
        )
      ORDER BY t.table_name
    LOOP
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS order_ids_open TEXT[] NOT NULL DEFAULT %L::text[]',
        sch, tbl, '{}'
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS order_ids_close TEXT[] NOT NULL DEFAULT %L::text[]',
        sch, tbl, '{}'
      );
      EXECUTE format(
        $q$
        UPDATE %I.%I
        SET order_ids_open = ARRAY[order_id_open]
        WHERE order_id_open IS NOT NULL
          AND NULLIF(TRIM(order_id_open), '') IS NOT NULL
          AND cardinality(order_ids_open) = 0
        $q$,
        sch, tbl
      );
      EXECUTE format(
        $q$
        UPDATE %I.%I
        SET order_ids_close = ARRAY[order_id_close]
        WHERE order_id_close IS NOT NULL
          AND NULLIF(TRIM(order_id_close), '') IS NOT NULL
          AND cardinality(order_ids_close) = 0
        $q$,
        sch, tbl
      );
    END LOOP;
  END LOOP;

  -- Archive live/paper trades tables (union parity)
  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS order_ids_open TEXT[] NOT NULL DEFAULT %L::text[]',
      tbl, '{}'
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS order_ids_close TEXT[] NOT NULL DEFAULT %L::text[]',
      tbl, '{}'
    );
    EXECUTE format(
      $q$
      UPDATE archive.%I
      SET order_ids_open = ARRAY[order_id_open]
      WHERE order_id_open IS NOT NULL
        AND NULLIF(TRIM(order_id_open), '') IS NOT NULL
        AND cardinality(order_ids_open) = 0
      $q$,
      tbl
    );
    EXECUTE format(
      $q$
      UPDATE archive.%I
      SET order_ids_close = ARRAY[order_id_close]
      WHERE order_id_close IS NOT NULL
        AND NULLIF(TRIM(order_id_close), '') IS NOT NULL
        AND cardinality(order_ids_close) = 0
      $q$,
      tbl
    );
  END LOOP;
END
$$;
