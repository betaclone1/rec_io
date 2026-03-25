DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT c.table_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'users'
          AND c.table_name LIKE 'active_trades_%'
          AND c.column_name = 'exchange'
          AND EXISTS (
              SELECT 1 FROM information_schema.columns c2
              WHERE c2.table_schema = 'users'
                AND c2.table_name = c.table_name
                AND c2.column_name = 'trade_id'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE users.%I RENAME COLUMN exchange TO market',
            r.table_name
        );
    END LOOP;
END $$;

ALTER TABLE users.trades_simulated_0001 RENAME COLUMN exchange TO market;

ALTER TABLE users.trades_0001 RENAME COLUMN exchange TO market;

ALTER TABLE live_data.market_kalshi_15m RENAME CONSTRAINT market_kalshi_15m_exchange_symbol_event_market_unique
    TO market_kalshi_15m_broker_symbol_event_market_unique;

ALTER TABLE live_data.market_kalshi_15m RENAME COLUMN exchange TO broker;

ALTER TABLE live_data.strike_table_15m RENAME COLUMN exchange TO broker;
