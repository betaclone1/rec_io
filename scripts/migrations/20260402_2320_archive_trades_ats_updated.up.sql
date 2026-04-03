-- Keep archive UNION column lists aligned with users.trades_0001 (union_trades_with_archives_select).
ALTER TABLE archive.trades_archive_live_0001
    ADD COLUMN IF NOT EXISTS ats_updated TIMESTAMPTZ;

ALTER TABLE archive.trades_archive_paper_0001
    ADD COLUMN IF NOT EXISTS ats_updated TIMESTAMPTZ;
