-- Rollback: remove NOTIFY trigger from users.trades_0001 (20260401_1600_trades_0001_rec_io_db_notify).

DROP TRIGGER IF EXISTS trades_0001_rec_io_db_notify ON users.trades_0001;
