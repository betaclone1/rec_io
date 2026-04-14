-- Move single-tenant data from schema "users" to "users_0001" (per-user silo naming).
-- Application code uses REC_USER_SCHEMA / tenant_context; default schema users_0001.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'users')
       AND NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'users_0001') THEN
        ALTER SCHEMA users RENAME TO users_0001;
    END IF;
END
$$;
