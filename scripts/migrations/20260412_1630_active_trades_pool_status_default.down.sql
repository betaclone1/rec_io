-- Revert status default on unified pool tables (per users_NNNN schema).
DO $$
DECLARE
    sch text;
    slot text;
    t15 text;
    th text;
BEGIN
    FOR sch IN
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name ~ '^users_[0-9]{4}$'
    LOOP
        slot := substring(sch from 7);
        t15 := 'active_trades_15m_' || slot;
        th := 'active_trades_hourly_' || slot;

        IF to_regclass(format('%I.%I', sch, t15)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN status DROP DEFAULT', sch, t15);
        END IF;

        IF to_regclass(format('%I.%I', sch, th)) IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN status DROP DEFAULT', sch, th);
        END IF;
    END LOOP;
END $$;
