-- New trade rows: monitor_confirmed unset until close logic writes true/false.
ALTER TABLE users.trades_0001
  ALTER COLUMN monitor_confirmed DROP DEFAULT,
  ALTER COLUMN monitor_confirmed SET DEFAULT NULL;

ALTER TABLE users.trades_simulated_0001
  ALTER COLUMN monitor_confirmed DROP DEFAULT,
  ALTER COLUMN monitor_confirmed SET DEFAULT NULL;
