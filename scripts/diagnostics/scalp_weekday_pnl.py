#!/usr/bin/env python3
"""Weekday breakdown for scalp strategies on prod trades_0001."""
from collections import defaultdict
from backend.core.config.database import get_system_postgresql_connection

conn = get_system_postgresql_connection()
cur = conn.cursor()

# Day of week in America/New_York from trade date/time
cur.execute(
    """
    WITH t AS (
      SELECT
        id,
        trade_strategy,
        win_loss,
        win_loss_confirmed,
        pnl,
        paper_trade,
        market,
        symbol,
        ((date::text || ' ' || COALESCE(time::text, '00:00:00'))::timestamp
          AT TIME ZONE 'America/New_York') AS ts_et,
        EXTRACT(DOW FROM ((date::text || ' ' || COALESCE(time::text, '00:00:00'))::timestamp
          AT TIME ZONE 'America/New_York')) AS dow,
        TO_CHAR(((date::text || ' ' || COALESCE(time::text, '00:00:00'))::timestamp
          AT TIME ZONE 'America/New_York'), 'Dy') AS dow_name,
        movement_percentile,
        movement,
        prob,
        buy_price,
        sell_price,
        close_method,
        status
      FROM users_0001.trades_0001
      WHERE trade_strategy ILIKE '%Scalp%'
        AND COALESCE(paper_trade, false) = false
        AND status = 'closed'
        AND win_loss_confirmed IS TRUE
    )
    SELECT
      trade_strategy,
      dow::int,
      dow_name,
      COUNT(*) AS n,
      COUNT(*) FILTER (WHERE win_loss = 'W') AS wins,
      COUNT(*) FILTER (WHERE win_loss = 'L') AS losses,
      ROUND(SUM(pnl)::numeric, 2) AS pnl_sum,
      ROUND(AVG(pnl)::numeric, 2) AS pnl_avg,
      ROUND(100.0 * COUNT(*) FILTER (WHERE win_loss = 'W') / NULLIF(COUNT(*), 0), 1) AS win_pct,
      ROUND(AVG(movement_percentile)::numeric, 1) AS avg_move_pctile,
      ROUND(AVG(movement)::numeric, 4) AS avg_movement,
      ROUND(AVG(prob)::numeric, 1) AS avg_prob,
      ROUND(AVG(buy_price)::numeric, 4) AS avg_buy
    FROM t
    GROUP BY 1, 2, 3
    ORDER BY 1, 2
    """
)
print("=== LIVE SCALP BY DOW (confirmed) ===")
rows = cur.fetchall()
cols = [d[0] for d in cur.description]
print("\t".join(cols))
for r in rows:
    print("\t".join("" if x is None else str(x) for x in r))

# Day-level: fraction of Saturdays that were net negative vs other days
# (calendar day P&L for Expiration Scalp)
cur.execute(
    """
    WITH t AS (
      SELECT
        date,
        EXTRACT(DOW FROM date::timestamp) AS dow,
        TO_CHAR(date::timestamp, 'Dy') AS dow_name,
        SUM(pnl) AS day_pnl,
        COUNT(*) AS n,
        COUNT(*) FILTER (WHERE win_loss = 'W') AS wins,
        COUNT(*) FILTER (WHERE win_loss = 'L') AS losses
      FROM users_0001.trades_0001
      WHERE trade_strategy = 'Expiration Scalp'
        AND COALESCE(paper_trade, false) = false
        AND status = 'closed'
        AND win_loss_confirmed IS TRUE
      GROUP BY 1, 2, 3
    )
    SELECT
      dow::int,
      dow_name,
      COUNT(*) AS days,
      COUNT(*) FILTER (WHERE day_pnl < 0) AS neg_days,
      COUNT(*) FILTER (WHERE day_pnl >= 0) AS nonneg_days,
      ROUND(100.0 * COUNT(*) FILTER (WHERE day_pnl < 0) / NULLIF(COUNT(*), 0), 1) AS pct_neg_days,
      ROUND(SUM(day_pnl)::numeric, 2) AS total_pnl,
      ROUND(AVG(day_pnl)::numeric, 2) AS avg_day_pnl,
      ROUND(SUM(n)::numeric, 0) AS trades,
      ROUND(AVG(100.0 * wins / NULLIF(n, 0))::numeric, 1) AS avg_day_win_pct
    FROM t
    GROUP BY 1, 2
    ORDER BY 1
    """
)
print("\n=== EXP SCALP CALENDAR-DAY PNL BY DOW ===")
cols = [d[0] for d in cur.description]
print("\t".join(cols))
for r in cur.fetchall():
    print("\t".join("" if x is None else str(x) for x in r))

# Close method mix by DOW for Exp Scalp (settlement vs stop)
cur.execute(
    """
    SELECT
      TO_CHAR(date::timestamp, 'Dy') AS dow_name,
      EXTRACT(DOW FROM date::timestamp)::int AS dow,
      COALESCE(close_method, '(null)') AS close_method,
      COUNT(*) AS n,
      ROUND(SUM(pnl)::numeric, 2) AS pnl,
      ROUND(100.0 * COUNT(*) FILTER (WHERE win_loss='W') / NULLIF(COUNT(*),0), 1) AS win_pct
    FROM users_0001.trades_0001
    WHERE trade_strategy = 'Expiration Scalp'
      AND COALESCE(paper_trade, false) = false
      AND status = 'closed'
      AND win_loss_confirmed IS TRUE
    GROUP BY 1, 2, 3
    ORDER BY 2, n DESC
    """
)
print("\n=== EXP SCALP CLOSE METHOD BY DOW ===")
cols = [d[0] for d in cur.description]
print("\t".join(cols))
for r in cur.fetchall():
    print("\t".join("" if x is None else str(x) for x in r))

# Date range
cur.execute(
    """
    SELECT MIN(date), MAX(date), COUNT(*)
    FROM users_0001.trades_0001
    WHERE trade_strategy = 'Expiration Scalp'
      AND COALESCE(paper_trade, false) = false
      AND win_loss_confirmed IS TRUE
    """
)
print("\n=== EXP SCALP SAMPLE ===", cur.fetchone())

conn.close()
