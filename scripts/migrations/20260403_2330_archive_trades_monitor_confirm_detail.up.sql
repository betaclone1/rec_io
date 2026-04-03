-- UNION (union_trades_with_archives_select) uses master column list; archive must match users.trades_0001.
ALTER TABLE archive.trades_archive_live_0001
    ADD COLUMN IF NOT EXISTS monitor_confirm_detail TEXT;

ALTER TABLE archive.trades_archive_paper_0001
    ADD COLUMN IF NOT EXISTS monitor_confirm_detail TEXT;
