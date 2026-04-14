-- Timestamp defaults/backfill are not safely reversible without restoring a prior dump
-- (dropping DEFAULT would break inserts that rely on DB defaults).
SELECT 1;
