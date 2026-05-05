-- Rename rollup metric columns from legacy ``{td|prev}_{d1|w1|m1|y1|all}_{metric}_{live|paper|ptest}``
-- to ``{1d|1w|1m|1y|all}_{td|prev}_{metric}_{live|paper|test}`` (matches trades-style window tokens).

DO $$
DECLARE
  sch text;
  rel text;
  col text;
  m text[];
  win2 text;
  md2 text;
  new_nm text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR rel IN
      SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = sch
        AND c.relkind = 'r'
        AND (
          c.relname ~ '^performance_total_[0-9]{4}$'
          OR c.relname ~ '^performance_monitors_[0-9]{4}$'
        )
    LOOP
      FOR col IN
        SELECT a.attname
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = sch
          AND c.relname = rel
          AND a.attnum > 0
          AND NOT a.attisdropped
      LOOP
        m := regexp_match(
          col,
          '^(td|prev)_(d1|w1|m1|y1|all)_(pnl|ret_pct|fees|trades_n|win_rate)_(live|paper|ptest)$'
        );
        IF m IS NULL THEN
          CONTINUE;
        END IF;
        win2 := CASE m[2]
          WHEN 'd1' THEN '1d'
          WHEN 'w1' THEN '1w'
          WHEN 'm1' THEN '1m'
          WHEN 'y1' THEN '1y'
          ELSE 'all'
        END;
        md2 := CASE m[4] WHEN 'ptest' THEN 'test' ELSE m[4] END;
        new_nm := win2 || '_' || m[1] || '_' || m[3] || '_' || md2;
        IF new_nm = col THEN
          CONTINUE;
        END IF;
        IF EXISTS (
          SELECT 1 FROM pg_attribute a2
          JOIN pg_class c2 ON c2.oid = a2.attrelid
          JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
          WHERE n2.nspname = sch AND c2.relname = rel AND a2.attname = new_nm AND a2.attnum > 0
        ) THEN
          RAISE NOTICE 'skip %.% % — target % already exists', sch, rel, col, new_nm;
          CONTINUE;
        END IF;
        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN %I TO %I', sch, rel, col, new_nm);
      END LOOP;
    END LOOP;
  END LOOP;
END
$$;
