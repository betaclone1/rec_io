-- Store buy/sell prices at 6 decimal places on tenant trades tables.
DO $$
DECLARE
  sch text;
  tbl text;
  sim_tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    tbl := replace('trades_0001', '0001', right(sch, 4));
    sim_tbl := replace('trades_simulated_0001', '0001', right(sch, 4));
    IF sch = 'users' THEN
      tbl := 'trades_0001';
      sim_tbl := 'trades_simulated_0001';
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = sch AND table_name = tbl
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN buy_price TYPE NUMERIC(12,6) USING ROUND(buy_price::numeric, 6)',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN sell_price TYPE NUMERIC(12,6) USING ROUND(sell_price::numeric, 6)',
        sch, tbl
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = sch AND table_name = sim_tbl
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN buy_price TYPE NUMERIC(12,6) USING ROUND(buy_price::numeric, 6)',
        sch, sim_tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN sell_price TYPE NUMERIC(12,6) USING ROUND(sell_price::numeric, 6)',
        sch, sim_tbl
      );
    END IF;
  END LOOP;
END
$$;
