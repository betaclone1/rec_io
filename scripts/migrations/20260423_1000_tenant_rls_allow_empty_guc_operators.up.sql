-- RLS: allow ad-hoc clients (TablePlus, psql, backups) that do NOT set rec.tenant_pg_schema
-- to see all rows in each users_NNNN table. When the GUC is set to a non-empty schema name,
-- behavior is unchanged (only that tenant's rows are visible for that table).
--
-- Application code should continue to set rec.tenant_pg_schema on every tenant connection.

DO $mig$
BEGIN
  EXECUTE $fn$
CREATE OR REPLACE FUNCTION rec.ensure_tenant_rls_for_schema(target_schema text)
RETURNS integer
LANGUAGE plpgsql
AS $body$
DECLARE
  n integer := 0;
  r record;
BEGIN
  IF target_schema !~ '^users_[0-9]{4}$' THEN
    RAISE EXCEPTION 'invalid tenant schema name: %', target_schema;
  END IF;

  FOR r IN
    SELECT c.relname AS tname
    FROM pg_class c
    JOIN pg_namespace ns ON ns.oid = c.relnamespace
    WHERE ns.nspname = target_schema
      AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', target_schema, r.tname);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', target_schema, r.tname);
    EXECUTE format('DROP POLICY IF EXISTS rec_tenant_gate ON %I.%I', target_schema, r.tname);
    EXECUTE format(
      $pol$
        CREATE POLICY rec_tenant_gate ON %I.%I
        FOR ALL
        USING (
          COALESCE(current_setting('rec.tenant_pg_schema', true), '') = ''
          OR COALESCE(current_setting('rec.tenant_pg_schema', true), '') = %L
        )
        WITH CHECK (
          COALESCE(current_setting('rec.tenant_pg_schema', true), '') = ''
          OR COALESCE(current_setting('rec.tenant_pg_schema', true), '') = %L
        )
      $pol$,
      target_schema,
      r.tname,
      target_schema,
      target_schema
    );
    n := n + 1;
  END LOOP;

  RETURN n;
END
$body$;
$fn$;

  PERFORM rec.refresh_all_tenant_rls();
END
$mig$;
