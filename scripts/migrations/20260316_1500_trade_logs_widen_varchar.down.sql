-- Revert widened varchar columns on users.trade_logs_0001 back to VARCHAR(50).
-- Values longer than 50 characters will be truncated on downgrade.

ALTER TABLE users.trade_logs_0001
    ALTER COLUMN ticket_id TYPE VARCHAR(50)
        USING LEFT(ticket_id, 50),
    ALTER COLUMN service TYPE VARCHAR(50)
        USING LEFT(service, 50),
    ALTER COLUMN user_id TYPE VARCHAR(50)
        USING LEFT(user_id, 50);

