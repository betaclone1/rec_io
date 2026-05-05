-- Pre-aggregated performance rollups: one totals row per tenant (performance_total_<slot>, user_id = 1)
-- and one row per monitor (performance_monitors_<slot>, PK column ``monitor``). Same metric column set on both.
-- NOTIFY via public.rec_io_db_notify → stream performance_rollups (see stream_registry).
-- Creates tables only for schemas that already have trades_<slot>.

DO $$
DECLARE
  sch text;
  trade_tbl text;
  slot text;
  tot text;
  mon text;
  col_defs text;
  sep text;
  kind text;
  win text;
  met text;
  md text;
  typ text;
  def text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR trade_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^trades_[0-9]{4}$'
    LOOP
      slot := (regexp_match(trade_tbl, 'trades_([0-9]{4})$'))[1];
      IF slot IS NULL THEN
        CONTINUE;
      END IF;
      tot := 'performance_total_' || slot;
      mon := 'performance_monitors_' || slot;

      -- Metric columns: ``{1d|1w|1m|1y|all}_{td|prev}_{metric}_{live|paper|test}`` (e.g. 1d_prev_pnl_paper).
      col_defs := '';
      sep := '';
      FOREACH win IN ARRAY ARRAY['1d', '1w', '1m', '1y', 'all'] LOOP
        FOREACH kind IN ARRAY ARRAY['td', 'prev'] LOOP
          FOREACH met IN ARRAY ARRAY['pnl', 'ret_pct', 'fees', 'trades_n', 'win_rate'] LOOP
            FOREACH md IN ARRAY ARRAY['live', 'paper', 'test'] LOOP
              IF met = 'trades_n' THEN
                typ := 'INTEGER';
                def := '0';
              ELSE
                typ := 'DOUBLE PRECISION';
                def := '0';
              END IF;
              col_defs := col_defs || sep
                || quote_ident(win || '_' || kind || '_' || met || '_' || md)
                || ' ' || typ || ' NOT NULL DEFAULT ' || def;
              sep := ', ';
            END LOOP;
          END LOOP;
        END LOOP;
      END LOOP;

      IF to_regclass(format('%I.%I', sch, tot)) IS NULL THEN
        EXECUTE format(
          'CREATE TABLE %I.%I (
            user_id INTEGER PRIMARY KEY DEFAULT 1 CHECK (user_id = 1),
            %s,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )',
          sch, tot, col_defs
        );
        EXECUTE format('INSERT INTO %I.%I (user_id) VALUES (1)', sch, tot);
        EXECUTE format(
          'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I.%I FOR EACH ROW EXECUTE PROCEDURE public.rec_io_db_notify()',
          tot || '_rec_io_db_notify', sch, tot
        );
      END IF;

      IF to_regclass(format('%I.%I', sch, mon)) IS NULL THEN
        EXECUTE format(
          'CREATE TABLE %I.%I (
            monitor TEXT PRIMARY KEY,
            %s,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )',
          sch, mon, col_defs
        );
        EXECUTE format(
          'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I.%I FOR EACH ROW EXECUTE PROCEDURE public.rec_io_db_notify()',
          mon || '_rec_io_db_notify', sch, mon
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
