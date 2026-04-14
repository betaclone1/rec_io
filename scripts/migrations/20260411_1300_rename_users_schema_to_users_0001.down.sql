DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'users_0001')
       AND NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'users') THEN
        ALTER SCHEMA users_0001 RENAME TO users;
    END IF;
END
$$;
