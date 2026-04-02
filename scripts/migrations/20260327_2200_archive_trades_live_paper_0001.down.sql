-- Revert archive trades mirror tables for user 0001 (drops data).

DROP TABLE IF EXISTS archive.trades_archive_paper_0001 CASCADE;
DROP TABLE IF EXISTS archive.trades_archive_live_0001 CASCADE;
DROP SEQUENCE IF EXISTS archive.trades_archive_paper_0001_id_seq CASCADE;
DROP SEQUENCE IF EXISTS archive.trades_archive_live_0001_id_seq CASCADE;
