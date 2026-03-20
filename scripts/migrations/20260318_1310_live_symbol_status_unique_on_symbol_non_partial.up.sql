-- Fix for trigger upsert:
-- Postgres does not reliably match partial unique indexes as an ON CONFLICT
-- target. Replace the partial unique index with a full-table unique index.

DROP INDEX IF EXISTS live_symbol_status_symbol_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS live_symbol_status_symbol_uniq_all
ON live_data.live_symbol_status USING btree (symbol);

