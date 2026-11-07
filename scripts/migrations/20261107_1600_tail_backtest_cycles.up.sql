-- Exact-cent Lower Tail / Upper Tail backtest outcomes per 15m cycle.
-- One table per series; LT and UT columns on the same row.
-- Source: public-trades tape + market_result cache (not live OB monitors).

CREATE SCHEMA IF NOT EXISTS historical_data;

DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'kxbtc15m_tail_backtest_cycles',
    'kxeth15m_tail_backtest_cycles',
    'kxsol15m_tail_backtest_cycles',
    'kxxrp15m_tail_backtest_cycles',
    'kxgold15m_tail_backtest_cycles',
    'kxsilver15m_tail_backtest_cycles',
    'kxwti15m_tail_backtest_cycles'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format($f$
      CREATE TABLE IF NOT EXISTS historical_data.%I (
        "timestamp" TIMESTAMP WITHOUT TIME ZONE NOT NULL,
        ticker TEXT NOT NULL,
        trading_day DATE NOT NULL,
        market_result TEXT,
        lt_fill_ts TIMESTAMP WITHOUT TIME ZONE,
        lt_side TEXT,
        lt_price NUMERIC(8, 4),
        lt_win_loss BOOLEAN,
        ut_fill_ts TIMESTAMP WITHOUT TIME ZONE,
        ut_side TEXT,
        ut_price NUMERIC(8, 4),
        ut_win_loss BOOLEAN,
        data_gap BOOLEAN NOT NULL DEFAULT FALSE,
        data_gap_reason TEXT,
        updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker),
        CONSTRAINT %I CHECK (market_result IS NULL OR market_result IN ('yes', 'no')),
        CONSTRAINT %I CHECK (lt_side IS NULL OR lt_side IN ('yes', 'no')),
        CONSTRAINT %I CHECK (ut_side IS NULL OR ut_side IN ('yes', 'no'))
      )
    $f$, t, t || '_mr_chk', t || '_lt_side_chk', t || '_ut_side_chk');

    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON historical_data.%I ("timestamp")',
      'idx_' || t || '_ts',
      t
    );
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON historical_data.%I (trading_day)',
      'idx_' || t || '_day',
      t
    );

    EXECUTE format(
      'COMMENT ON TABLE historical_data.%I IS %L',
      t,
      'Per-cycle exact-cent LT ($0.01) and UT ($0.99) backtest outcomes from public trades; '
      || 'win_loss NULL when no fill or unsettled. timestamp = cycle settlement end ET naive.'
    );
    EXECUTE format(
      'COMMENT ON COLUMN historical_data.%I."timestamp" IS %L',
      t,
      'Cycle settlement end as US Eastern wall time (timestamp without time zone).'
    );
  END LOOP;
END $$;
