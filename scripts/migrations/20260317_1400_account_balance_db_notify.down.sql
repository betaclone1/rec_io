-- Remove NOTIFY trigger from users.account_balance_0001 (rollback for 20260317_1400_account_balance_db_notify).

DROP TRIGGER IF EXISTS account_balance_0001_db_notify ON users.account_balance_0001;

