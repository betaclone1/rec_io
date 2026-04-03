-- Restore previous default (does not re-FALSE in-flight rows that were cleared to NULL).

ALTER TABLE users.trades_0001
  ALTER COLUMN monitor_confirmed SET DEFAULT FALSE;

ALTER TABLE users.trades_simulated_0001
  ALTER COLUMN monitor_confirmed SET DEFAULT FALSE;
