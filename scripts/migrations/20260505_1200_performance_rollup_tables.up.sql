-- Original DDL attempted unquoted identifiers such as ``1d_td_pnl_live``, which PostgreSQL rejects
-- (identifiers cannot start with a digit unless quoted). Real rollup CREATE lives in
-- ``20260505_1400_performance_rollup_tables.up.sql`` (uses ``quote_ident`` for window-prefixed names).
-- This migration id is retained as a no-op so ordering and ``schema_migrations`` stay consistent.

SELECT 1;
