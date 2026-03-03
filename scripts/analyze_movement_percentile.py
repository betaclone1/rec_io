#!/usr/bin/env python3
"""
Analyze movement_percentile vs cycle win/loss for monitor 10020.
Percentile only. Cycle = (contract, date); one cycle = one W or L.
Run from repo root: python3 scripts/analyze_movement_percentile.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config.database import get_postgresql_connection


def run_query(conn, query):
    cur = conn.cursor()
    cur.execute(query)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close()
    return rows, cols


def main():
    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to database")
        return 1

    # Cycle = (contract, date). Use first leg (min id) for entry metrics.
    base = """
    WITH cycle_first_leg AS (
        SELECT t.contract, t.date, MIN(t.id) AS first_id
        FROM users.trades_0001 t
        WHERE t.monitor = 'mon_0001_10020' AND t.symbol = 'BTC'
          AND t.contract IS NOT NULL AND t.date IS NOT NULL
        GROUP BY t.contract, t.date
    ),
    cycles AS (
        SELECT t.contract, t.date, t.momentum_percentile, t.movement_percentile, t.cycle_win_loss AS cwl
        FROM users.trades_0001 t
        JOIN cycle_first_leg c ON t.contract = c.contract AND t.date = c.date AND t.id = c.first_id
        WHERE t.monitor = 'mon_0001_10020' AND t.symbol = 'BTC'
    )
    """

    print("=" * 60)
    print("1. MOVEMENT_PERCENTILE vs CYCLE W/L (428 cycles)")
    print("=" * 60)
    rows, _ = run_query(conn, base + """
    SELECT
        CASE
            WHEN movement_percentile < 20 THEN '0-20'
            WHEN movement_percentile < 40 THEN '20-40'
            WHEN movement_percentile < 60 THEN '40-60'
            WHEN movement_percentile < 80 THEN '60-80'
            ELSE '80-100'
        END AS bucket,
        COUNT(*) AS cycles,
        SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) AS wins,
        SUM(CASE WHEN cwl = 'L' THEN 1 ELSE 0 END) AS losses,
        ROUND(100.0 * SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_pct
    FROM cycles
    WHERE movement_percentile IS NOT NULL
    GROUP BY bucket
    ORDER BY MIN(movement_percentile)
    """)
    print(f"{'Bucket':<12} {'Cycles':>8} {'Wins':>6} {'Losses':>7} {'Win%':>8}")
    for r in rows:
        print(f"{r[0]:<12} {r[1]:>8} {r[2]:>6} {r[3]:>7} {r[4]:>8}")

    print()
    print("=" * 60)
    print("2. MOMENTUM + MOVEMENT PERCENTILE overlap")
    print("=" * 60)
    rows, _ = run_query(conn, base + """
    SELECT
        CASE
            WHEN ABS(momentum_percentile) < 50 THEN 'mom 0-50'
            WHEN ABS(momentum_percentile) < 70 THEN 'mom 50-70'
            WHEN ABS(momentum_percentile) < 90 THEN 'mom 70-90'
            ELSE 'mom 90+'
        END AS mom_bucket,
        CASE
            WHEN movement_percentile < 50 THEN 'mov 0-50'
            WHEN movement_percentile < 70 THEN 'mov 50-70'
            ELSE 'mov 70+'
        END AS mov_bucket,
        COUNT(*) AS cycles,
        SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) AS wins,
        SUM(CASE WHEN cwl = 'L' THEN 1 ELSE 0 END) AS losses,
        ROUND(100.0 * SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_pct
    FROM cycles
    WHERE momentum_percentile IS NOT NULL AND movement_percentile IS NOT NULL
    GROUP BY mom_bucket, mov_bucket
    ORDER BY mom_bucket, mov_bucket
    """)
    print(f"{'Mom':<12} {'Mov':<12} {'Cycles':>8} {'Wins':>6} {'Losses':>7} {'Win%':>8}")
    for r in rows:
        print(f"{r[0]:<12} {r[1]:<12} {r[2]:>8} {r[3]:>6} {r[4]:>7} {r[5]:>8}")

    print()
    print("3. SWEET SPOT: |momentum| 70-90 + movement 70+")
    rows, _ = run_query(conn, base + """
    SELECT COUNT(*) AS cycles,
           SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) AS wins,
           SUM(CASE WHEN cwl = 'L' THEN 1 ELSE 0 END) AS losses,
           ROUND(100.0 * SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_pct
    FROM cycles
    WHERE ABS(momentum_percentile) >= 70 AND ABS(momentum_percentile) < 90 AND movement_percentile >= 70
    """)
    r = rows[0]
    print(f"Cycles: {r[0]}, Wins: {r[1]}, Losses: {r[2]}, Win%: {r[3]}")

    print()
    print("4. BASELINE")
    rows, _ = run_query(conn, base + """
    SELECT COUNT(*) AS cycles,
           SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) AS wins,
           SUM(CASE WHEN cwl = 'L' THEN 1 ELSE 0 END) AS losses,
           ROUND(100.0 * SUM(CASE WHEN cwl = 'W' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_pct
    FROM cycles
    WHERE movement_percentile IS NOT NULL
    """)
    r = rows[0]
    print(f"Cycles: {r[0]}, Wins: {r[1]}, Losses: {r[2]}, Win%: {r[3]}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
