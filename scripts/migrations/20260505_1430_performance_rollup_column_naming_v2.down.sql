-- Reverse v2 naming: ``{1d|...}_{td|prev}_{metric}_{live|paper|test}`` → legacy ``{td|prev}_{d1|...}_{metric}_{live|paper|ptest}``.

DO $$
DECLARE
  sch text;
  rel text;
  col text;
  m text[];
  winl text;
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
          '^(1d|1w|1m|1y|all)_(td|prev)_(pnl|ret_pct|fees|trades_n|win_rate)_(live|paper|test)$'
        );
        IF m IS NULL THEN
          CONTINUE;
        END IF;
        winl := CASE m[1]
          WHEN '1d' THEN 'd1'
          WHEN '1w' THEN 'w1'
          WHEN '1m' THEN 'm1'
          WHEN '1y' THEN 'y1'
          ELSE 'all'
        END;
        md2 := CASE m[4] WHEN 'test' THEN 'ptest' ELSE m[4] END;
        new_nm := m[2] || '_' || winl || '_' || m[3] || '_' || md2;
        IF new_nm = col THEN
          CONTINUE;
        END IF;
        IF EXISTS (
          SELECT 1 FROM pg_attribute a2
          JOIN pg_class c2 ON c2.oid = a2.attrelid
          JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
          WHERE n2.nspname = sch AND c2.relname = rel AND a2.attname = new_nm AND a2.attnum > 0
        ) THEN
          CONTINUE;
        END IF;
        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN %I TO %I', sch, rel, col, new_nm);
      END LOOP;
    END LOOP;
  END LOOP;
END
$$;
