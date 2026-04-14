-- Installations that applied 20260409_2200 before it created strategy_list_default still have system.strategy_list.
DO $$
BEGIN
    IF to_regclass('system.strategy_list') IS NOT NULL
       AND to_regclass('system.strategy_list_default') IS NULL THEN
        ALTER TABLE system.strategy_list RENAME TO strategy_list_default;
    END IF;
END
$$;
