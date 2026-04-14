DO $$
BEGIN
    IF to_regclass('system.strategy_list_default') IS NOT NULL
       AND to_regclass('system.strategy_list') IS NULL THEN
        ALTER TABLE system.strategy_list_default RENAME TO strategy_list;
    END IF;
END
$$;
