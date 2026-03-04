#!/usr/bin/env python3
"""
Spot-check movement and movement_percentile in historical_data.btc_price_history and eth_price_history.
Run from repo root: python -m backend.util.analytics.verify_movement_spotcheck
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.config.database import get_postgresql_connection


def main():
    conn = get_postgresql_connection()
    if not conn:
        print("Cannot connect to PostgreSQL")
        return 1

    for symbol in ["btc", "eth"]:
        table = f"historical_data.{symbol}_price_history"
        print(f"\n=== {symbol.upper()} ({table}) ===")
        cur = conn.cursor()

        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'historical_data' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (f"{symbol}_price_history",),
        )
        cols = [r[0] for r in cur.fetchall()]
        has_mov = "movement" in cols
        has_pct = "movement_percentile" in cols
        print(f"Columns: movement={has_mov}, movement_percentile={has_pct}")
        if not has_mov or not has_pct:
            print("  FAIL: missing movement or movement_percentile")
            cur.close()
            continue

        cur.execute(
            f"SELECT COUNT(*), COUNT(movement), COUNT(movement_percentile) FROM {table}"
        )
        total, n_mov, n_pct = cur.fetchone()
        print(f"Rows: total={total}, movement non-null={n_mov}, movement_percentile non-null={n_pct}")

        cur.execute(
            f"""
            SELECT timestamp, open, high, low, close, movement, movement_percentile
            FROM {table}
            WHERE movement IS NOT NULL AND movement_percentile IS NOT NULL
            ORDER BY timestamp
            LIMIT 20
            """
        )
        rows = cur.fetchall()
        names = [d[0] for d in cur.description]
        print("\nSample 20 rows (first 20 with both movement and movement_percentile):")
        print("-" * 110)
        for r in rows:
            row = dict(zip(names, r))
            ts = str(row["timestamp"])[:19]
            o, h, l_ = row["open"], row["high"], row["low"]
            mov, pct = row["movement"], row["movement_percentile"]
            raw_range = (float(h) - float(l_)) / float(o) * 100 if o else None
            print(f"  {ts}  O={o} H={h} L={l_}  movement={mov}  movement_pct={pct}  (raw range%={raw_range:.2f})")

        cur.execute(
            f"""
            SELECT MIN(movement), MAX(movement), MIN(movement_percentile), MAX(movement_percentile)
            FROM {table} WHERE movement IS NOT NULL AND movement_percentile IS NOT NULL
            """
        )
        min_m, max_m, min_p, max_p = cur.fetchone()
        print(f"\nRanges: movement [{min_m}, {max_m}], movement_percentile [{min_p}, {max_p}]")
        if min_p is not None and (float(min_p) < 0 or float(max_p) > 100):
            print("  WARN: movement_percentile outside [0, 100]")
        cur.close()

    conn.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
