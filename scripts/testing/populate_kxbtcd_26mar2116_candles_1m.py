#!/usr/bin/env python3
"""
Thin wrapper for KXBTCD-26MAR2116-T70399.99. Prefer:
  scripts/testing/populate_kalshi_testing_candles_1m.py --ticker KXBTCD-26MAR2116-T70399.99
"""

from __future__ import annotations

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
HELPERS = os.path.join(PROJECT_ROOT, "scripts", "backtest", "helpers")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, HELPERS)

from backend.core.config.database import get_postgresql_connection  # noqa: E402
from kalshi_candles_1m import run_fill  # noqa: E402

MARKET = "KXBTCD-26MAR2116-T70399.99"


def main() -> None:
    conn = get_postgresql_connection()
    if not conn:
        print("DB connection failed")
        sys.exit(1)
    try:
        open_u, close_u, n = run_fill(conn, MARKET, "KXBTCD")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(e)
        sys.exit(1)
    finally:
        conn.close()
    print(f"Upserted {n} rows into testing.\"candlesticks_1m_{MARKET}\"")
    print(f"Window unix: {open_u} .. {close_u} ({n} candles from API)")


if __name__ == "__main__":
    main()
