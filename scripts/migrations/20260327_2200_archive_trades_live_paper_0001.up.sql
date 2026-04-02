-- Per-monitor trade archival: mirror users.trades_0001 into archive.trades_archive_live_0001 and
-- archive.trades_archive_paper_0001 (plus archived_at). No NOTIFY trigger on archive tables.
-- Application: backend.util.trade_log_archivist

DO $archive_trades_tables$
BEGIN
  CREATE SCHEMA IF NOT EXISTS archive;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'archive' AND table_name = 'trades_archive_live_0001'
  ) THEN
    CREATE TABLE archive.trades_archive_live_0001 (
      LIKE users.trades_0001 INCLUDING CONSTRAINTS INCLUDING INDEXES EXCLUDING DEFAULTS
    );
    ALTER TABLE archive.trades_archive_live_0001
      ADD COLUMN archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    CREATE SEQUENCE archive.trades_archive_live_0001_id_seq;
    ALTER TABLE archive.trades_archive_live_0001
      ALTER COLUMN id SET DEFAULT nextval('archive.trades_archive_live_0001_id_seq'::regclass);
    ALTER SEQUENCE archive.trades_archive_live_0001_id_seq
      OWNED BY archive.trades_archive_live_0001.id;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'archive' AND table_name = 'trades_archive_paper_0001'
  ) THEN
    CREATE TABLE archive.trades_archive_paper_0001 (
      LIKE users.trades_0001 INCLUDING CONSTRAINTS INCLUDING INDEXES EXCLUDING DEFAULTS
    );
    ALTER TABLE archive.trades_archive_paper_0001
      ADD COLUMN archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
    CREATE SEQUENCE archive.trades_archive_paper_0001_id_seq;
    ALTER TABLE archive.trades_archive_paper_0001
      ALTER COLUMN id SET DEFAULT nextval('archive.trades_archive_paper_0001_id_seq'::regclass);
    ALTER SEQUENCE archive.trades_archive_paper_0001_id_seq
      OWNED BY archive.trades_archive_paper_0001.id;
  END IF;

  EXECUTE $idx_live$
    CREATE INDEX IF NOT EXISTS idx_trades_archive_live_0001_monitor
      ON archive.trades_archive_live_0001 (monitor)
  $idx_live$;

  EXECUTE $idx_paper$
    CREATE INDEX IF NOT EXISTS idx_trades_archive_paper_0001_monitor
      ON archive.trades_archive_paper_0001 (monitor)
  $idx_paper$;

  EXECUTE 'GRANT ALL ON SCHEMA archive TO rec_io_user';
  EXECUTE 'GRANT ALL ON ALL TABLES IN SCHEMA archive TO rec_io_user';
  EXECUTE 'GRANT ALL ON ALL SEQUENCES IN SCHEMA archive TO rec_io_user';
END
$archive_trades_tables$;
