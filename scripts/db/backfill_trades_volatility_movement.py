#!/usr/bin/env python3
"""
Backfill users.trades_0001 volatility, volatility_percentile, movement, movement_percentile
from historical_data.{btc|eth}_price_history using the top-of-minute EST timestamp for each trade.

Symbol on the trade row determines the table (BTC -> btc_price_history, ETH -> eth_price_history).
Historical price timestamps are EST (stored as timestamp without time zone).

Run from repo root: python3 scripts/backfill_trades_volatility_movement.py
"""
import os
import sys
from datetime import datetime, date, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.core.config.database import get_postgresql_connection


def _top_of_minute_est(date_val, time_val):
    """Build EST top-of-minute timestamp from trade date and time (assumed EST)."""
    if date_val is None or time_val is None:
        return None
    if hasattr(date_val, "strftime"):
        d = date_val
    else:
        try:
            d = datetime.strptime(str(date_val).strip()[:10], "%Y-%m-%d").date()
        except Exception:
            return None
    if hasattr(time_val, "hour"):
        t = time_val
    else:
        try:
            s = str(time_val).strip()
            if len(s) >= 8:
                t = datetime.strptime(s[:8], "%H:%M:%S").time()
            elif len(s) >= 5:
                t = datetime.strptime(s[:5] + ":00", "%H:%M:%S").time()
            else:
                return None
        except Exception:
            return None
    dt = datetime.combine(d, t)
    return dt.replace(second=0, microsecond=0)


def _symbol_to_table(symbol):
    """Return historical_data table name (btc_price_history or eth_price_history) or None."""
    if not symbol:
        return None
    s = str(symbol).strip().upper()
    if s == "BTC":
        return "historical_data.btc_price_history"
    if s == "ETH":
        return "historical_data.eth_price_history"
    return None


def main():
    conn = get_postgresql_connection()
    if not conn:
        print("Cannot connect to PostgreSQL")
        return 1

    cur = conn.cursor()

    # Trades that need backfill: symbol is BTC or ETH and at least one of the four columns is null
    cur.execute("""
        SELECT id, symbol, date, time
        FROM users.trades_0001
        WHERE symbol IS NOT NULL
          AND UPPER(TRIM(symbol)) IN ('BTC', 'ETH')
          AND (
              volatility IS NULL
              OR volatility_percentile IS NULL
              OR movement IS NULL
              OR movement_percentile IS NULL
          )
        ORDER BY id
    """)
    rows = cur.fetchall()
    if not rows:
        print("No trades need backfill.")
        cur.close()
        conn.close()
        return 0

    print(f"Found {len(rows)} trades to backfill.")

    updated = 0
    skipped_no_ts = 0
    skipped_no_row = 0
    errors = 0

    for (tid, symbol, date_val, time_val) in rows:
        minute_ts = _top_of_minute_est(date_val, time_val)
        if minute_ts is None:
            skipped_no_ts += 1
            continue

        table = _symbol_to_table(symbol)
        if not table:
            continue

        cur.execute(
            f"""
            SELECT volatility, volatility_percentile, movement, movement_percentile
            FROM {table}
            WHERE timestamp = %s
            """,
            (minute_ts,),
        )
        hist = cur.fetchone()
        if not hist or all(x is None for x in hist):
            skipped_no_row += 1
            continue

        vol, vol_pct, mov, mov_pct = hist
        try:
            cur.execute(
                """
                UPDATE users.trades_0001
                SET volatility = COALESCE(%s, volatility),
                    volatility_percentile = COALESCE(%s, volatility_percentile),
                    movement = COALESCE(%s, movement),
                    movement_percentile = COALESCE(%s, movement_percentile)
                WHERE id = %s
                """,
                (vol, vol_pct, mov, mov_pct, tid),
            )
            if cur.rowcount:
                updated += 1
        except Exception as e:
            errors += 1
            print(f"Error updating trade id={tid}: {e}")

    conn.commit()
    cur.close()
    conn.close()

    print(f"Updated: {updated}, skipped (no timestamp): {skipped_no_ts}, skipped (no historical row): {skipped_no_row}, errors: {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
