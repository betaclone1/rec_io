-- Roll back master strike archive table.
-- Note: drops all monthly partitions via CASCADE.

DROP TABLE IF EXISTS historical_data.strike_table_master CASCADE;
