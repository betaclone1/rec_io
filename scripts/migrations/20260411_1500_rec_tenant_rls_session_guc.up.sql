-- Database-enforced tenant isolation for schemas users_NNNN (single statement for migration runner).
-- Session GUC rec.tenant_pg_schema must match the table's schema (set by TenantConnection via set_config).
-- After new tenant tables: SELECT rec.refresh_all_tenant_rls();
--
-- If set_config fails from the app, add: custom_variable_classes = 'rec' to postgresql.conf
--
-- IMPORTANT: PostgreSQL superusers always bypass RLS. Application connections must use a
-- non-superuser role (e.g. set DB_USER to a dedicated role) or ALTER ROLE ... NOSUPERUSER on
-- the app role so policies actually restrict cross-tenant access.

DO $rec_tenant_rls$
DECLARE
  r_schema record;
BEGIN
  EXECUTE 'CREATE SCHEMA IF NOT EXISTS rec';

  EXECUTE $fn1$
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
        USING (COALESCE(current_setting('rec.tenant_pg_schema', true), '') = %L)
        WITH CHECK (COALESCE(current_setting('rec.tenant_pg_schema', true), '') = %L)
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
$fn1$;

  EXECUTE $fn2$
CREATE OR REPLACE FUNCTION rec.refresh_all_tenant_rls()
RETURNS integer
LANGUAGE plpgsql
AS $body2$
DECLARE
  s text;
  t integer := 0;
BEGIN
  FOR s IN
    SELECT schema_name
    FROM information_schema.schemata
    WHERE schema_name ~ '^users_[0-9]{4}$'
  LOOP
    t := t + rec.ensure_tenant_rls_for_schema(s);
  END LOOP;
  RETURN t;
END
$body2$;
$fn2$;

  FOR r_schema IN
    SELECT schema_name AS s
    FROM information_schema.schemata
    WHERE schema_name ~ '^users_[0-9]{4}$'
  LOOP
    PERFORM rec.ensure_tenant_rls_for_schema(r_schema.s);
  END LOOP;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rec_io_user') THEN
    EXECUTE 'ALTER ROLE rec_io_user NOBYPASSRLS';
  END IF;

  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rec_io_user') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA rec TO rec_io_user';
    EXECUTE 'GRANT EXECUTE ON FUNCTION rec.ensure_tenant_rls_for_schema(text) TO rec_io_user';
    EXECUTE 'GRANT EXECUTE ON FUNCTION rec.refresh_all_tenant_rls() TO rec_io_user';
  END IF;
END
$rec_tenant_rls$;
