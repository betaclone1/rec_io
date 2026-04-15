#!/usr/bin/env python3
"""
Ensure monthly partitions exist for historical_data.strike_table_master.

Usage:
  PYTHONPATH=$(pwd) python3 scripts/db/maintain_strike_archive_partitions.py --months-ahead 2
"""

from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.core.config.database import get_system_postgresql_connection
from backend.historical_strike_table_archive import ensure_master_table, ensure_partitions_months_ahead


def main() -> int:
    p = argparse.ArgumentParser(description="Ensure strike archive monthly partitions exist.")
    p.add_argument(
        "--months-ahead",
        type=int,
        default=2,
        help="Create partitions for current month + N future months (default: 2).",
    )
    args = p.parse_args()

    conn = get_system_postgresql_connection()
    if not conn:
        print("failed to open DB connection", file=sys.stderr)
        return 1
    try:
        with conn.cursor() as cur:
            ensure_master_table(cur)
            rels = ensure_partitions_months_ahead(cur, months_ahead=args.months_ahead)
        conn.commit()
        print(f"ensured {len(rels)} partition(s): {', '.join(rels)}")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
