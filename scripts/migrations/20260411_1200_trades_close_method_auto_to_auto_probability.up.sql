-- Backfill: legacy ATS stored close_method = 'auto' for probability auto-stop when trigger_reason was unknown.
-- Align historical rows with explicit code (e.g. active_trade_supervisor._close_method_for_auto_trigger → auto_probability).

UPDATE users.trades_0001
SET close_method = 'auto_probability'
WHERE TRIM(LOWER(COALESCE(close_method, ''))) = 'auto';

UPDATE users.trades_simulated_0001
SET close_method = 'auto_probability'
WHERE TRIM(LOWER(COALESCE(close_method, ''))) = 'auto';

UPDATE archive.trades_archive_live_0001
SET close_method = 'auto_probability'
WHERE TRIM(LOWER(COALESCE(close_method, ''))) = 'auto';

UPDATE archive.trades_archive_paper_0001
SET close_method = 'auto_probability'
WHERE TRIM(LOWER(COALESCE(close_method, ''))) = 'auto';

DO $legacy_archive$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'archive' AND table_name = 'trades_0001_archive_20251003'
  ) THEN
    UPDATE archive.trades_0001_archive_20251003
    SET close_method = 'auto_probability'
    WHERE TRIM(LOWER(COALESCE(close_method, ''))) = 'auto';
  END IF;
END
$legacy_archive$;
