#!/usr/bin/env python3
"""
Upsert Kalshi 1m candlesticks for open_time..close_time into
testing."candlesticks_1m_<ticker>" (table must exist from a migration).

Uses live series candlesticks first; falls back to historical if needed.

  .venv/bin/python3 scripts/testing/populate_kalshi_testing_candles_1m.py \\
    --ticker KXBTCD-26JAN1320-T95499.99

Optional: --series KXBTCD (default: first segment of ticker before '-')
"""

from __future__ import annotations

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
HELPERS = os.path.join(PROJECT_ROOT, "scripts", "backtest", "helpers")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, HELPERS)

from backend.core.config.database import get_postgresql_connection  # noqa: E402
from kalshi_candles_1m import run_fill  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Fill testing.candlesticks_1m_<ticker> from Kalshi API.")
    p.add_argument("--ticker", required=True, help="Full market ticker, e.g. KXBTCD-26JAN1320-T95499.99")
    p.add_argument("--series", default=None, help="Series ticker (default: segment before first '-' in ticker)")
    args = p.parse_args()

    conn = get_postgresql_connection()
    if not conn:
        print("DB connection failed")
        sys.exit(1)

    try:
        open_u, close_u, n = run_fill(conn, args.ticker, args.series)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
        sys.exit(1)
    finally:
        conn.close()

    print(f"Upserted {n} rows into testing.\"candlesticks_1m_{args.ticker}\"")
    print(f"Window unix: {open_u} .. {close_u}")


if __name__ == "__main__":
    main()
