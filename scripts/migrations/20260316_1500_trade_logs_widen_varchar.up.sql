-- Widen varchar columns on users.trade_logs_0001 to avoid truncation errors when
-- logging trade events with longer ticket IDs, service names, or user IDs.
--
-- This aligns ticket_id and related identifiers with other tables that already
-- use wider varchar lengths (e.g. trades_0001.ticket_id VARCHAR(100)).

ALTER TABLE users.trade_logs_0001
    ALTER COLUMN ticket_id TYPE VARCHAR(100)
        USING ticket_id::VARCHAR(100),
    ALTER COLUMN service TYPE VARCHAR(100)
        USING service::VARCHAR(100),
    ALTER COLUMN user_id TYPE VARCHAR(100)
        USING user_id::VARCHAR(100);

