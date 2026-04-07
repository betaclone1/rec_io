-- Test-filter monitors are paper-only: align paper_trade for any row left inconsistent.

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'monitor_list_%'
  LOOP
    EXECUTE format(
      'UPDATE users.%I SET paper_trade = TRUE WHERE COALESCE(test_filter, FALSE) = TRUE AND COALESCE(paper_trade, FALSE) = FALSE',
      tbl
    );
  END LOOP;
END
$$;
