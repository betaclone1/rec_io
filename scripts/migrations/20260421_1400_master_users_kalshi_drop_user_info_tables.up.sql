-- Kalshi v1 account id moves to system.master_users; drop legacy users*.user_info_NNNN tables.

ALTER TABLE system.master_users
    ADD COLUMN IF NOT EXISTS kalshi_user_id VARCHAR(64);

-- Backfill kalshi_user_id from any existing user_info_<slot> table (users or users_MMMM schema).
DO $$
DECLARE
    r RECORD;
    slot text;
    has_kalshi boolean;
BEGIN
    FOR r IN
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name ~ '^user_info_[0-9]{4}$'
    LOOP
        slot := (regexp_match(r.table_name, '^user_info_([0-9]{4})$'))[1];
        IF slot IS NULL THEN
            CONTINUE;
        END IF;
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns c
            WHERE c.table_schema = r.table_schema
              AND c.table_name = r.table_name
              AND c.column_name = 'kalshi_user_id'
        ) INTO has_kalshi;
        IF NOT has_kalshi THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            $q$
            UPDATE system.master_users mu
            SET kalshi_user_id = COALESCE(NULLIF(TRIM(v.kalshi_user_id::text), ''), mu.kalshi_user_id)
            FROM (
                SELECT kalshi_user_id
                FROM %I.%I
                WHERE LPAD(TRIM(user_no::text), 4, '0') = %L
                LIMIT 1
            ) v
            WHERE LPAD(TRIM(mu.user_no::text), 4, '0') = %L
            $q$,
            r.table_schema,
            r.table_name,
            slot,
            slot
        );
    END LOOP;
END $$;

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name ~ '^user_info_[0-9]{4}$'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.%I CASCADE', r.table_schema, r.table_name);
    END LOOP;
END $$;
