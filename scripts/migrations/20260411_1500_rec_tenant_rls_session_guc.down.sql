-- Reverse 20260411_1500_rec_tenant_rls_session_guc (single statement).

DO $down_rec_tenant_rls$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT n.nspname AS sch, c.relname AS tname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname ~ '^users_[0-9]{4}$'
      AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS rec_tenant_gate ON %I.%I', r.sch, r.tname);
    EXECUTE format('ALTER TABLE %I.%I NO FORCE ROW LEVEL SECURITY', r.sch, r.tname);
    EXECUTE format('ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY', r.sch, r.tname);
  END LOOP;

  EXECUTE 'DROP FUNCTION IF EXISTS rec.refresh_all_tenant_rls()';
  EXECUTE 'DROP FUNCTION IF EXISTS rec.ensure_tenant_rls_for_schema(text)';
  EXECUTE 'DROP SCHEMA IF EXISTS rec';
END
$down_rec_tenant_rls$;
