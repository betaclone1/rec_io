-- Remove ATS operational audit table (logging uses standard app logs, not Postgres rows).
DROP TABLE IF EXISTS users.ats_monitoring_events;
