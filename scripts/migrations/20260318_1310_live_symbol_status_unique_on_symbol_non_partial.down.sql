-- Revert unique index replacement for trigger upsert.

DROP INDEX IF EXISTS live_symbol_status_symbol_uniq_all;

-- Restore the partial unique index variant.
CREATE UNIQUE INDEX IF NOT EXISTS live_symbol_status_symbol_uniq
ON live_data.live_symbol_status USING btree (symbol)
WHERE symbol IS NOT NULL;

