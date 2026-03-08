-- Revert: remove kalshi_id, vendor, rail and unique index from users.account_history_0001.
DROP INDEX IF EXISTS users.account_history_0001_kalshi_id_key;
ALTER TABLE users.account_history_0001 DROP COLUMN IF EXISTS kalshi_id;
ALTER TABLE users.account_history_0001 DROP COLUMN IF EXISTS vendor;
ALTER TABLE users.account_history_0001 DROP COLUMN IF EXISTS rail;
