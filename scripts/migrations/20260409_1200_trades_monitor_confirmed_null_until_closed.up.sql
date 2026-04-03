-- monitor_confirmed is meaningful only after finalize (closed/expired). In-flight rows must be NULL, not FALSE.

ALTER TABLE users.trades_0001
  ALTER COLUMN monitor_confirmed DROP DEFAULT,
  ALTER COLUMN monitor_confirmed SET DEFAULT NULL;

UPDATE users.trades_0001
SET monitor_confirmed = NULL
WHERE status NOT IN ('closed', 'expired');

ALTER TABLE users.trades_simulated_0001
  ALTER COLUMN monitor_confirmed DROP DEFAULT,
  ALTER COLUMN monitor_confirmed SET DEFAULT NULL;

UPDATE users.trades_simulated_0001
SET monitor_confirmed = NULL
WHERE UPPER(TRIM(COALESCE(status, ''))) NOT IN ('CLOSED', 'EXPIRED');
