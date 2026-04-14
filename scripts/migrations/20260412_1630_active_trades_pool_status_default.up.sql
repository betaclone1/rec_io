-- Unified pool tables per tenant (active_trades_15m_NNNN, active_trades_hourly_NNNN):
-- some schemas were created without DEFAULT 'active' on status, so INSERTs that omit status
-- stored NULL and the ATS monitoring COUNT excluded those rows (only active/pending/closing).
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
            EXECUTE format(
                'UPDATE %I.%I SET status = %L WHERE status IS NULL',
                sch,
                t15,
                'active'
            );
            EXECUTE format(
                'ALTER TABLE %I.%I ALTER COLUMN status SET DEFAULT %L',
                sch,
                t15,
                'active'
            );
        END IF;

        IF to_regclass(format('%I.%I', sch, th)) IS NOT NULL THEN
            EXECUTE format(
                'UPDATE %I.%I SET status = %L WHERE status IS NULL',
                sch,
                th,
                'active'
            );
            EXECUTE format(
                'ALTER TABLE %I.%I ALTER COLUMN status SET DEFAULT %L',
                sch,
                th,
                'active'
            );
        END IF;
    END LOOP;
END $$;
