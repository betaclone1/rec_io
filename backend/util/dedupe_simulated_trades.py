#!/usr/bin/env python3
"""
ONE-TIME CLEANUP ONLY. Do not run again.

Used once to remove duplicates that accumulated before AES used the correct DB
connection for is_strike_already_simulated_traded. Duplicate prevention is now
in-app; no recurring dedupe needed.

Note: This script deduped by (date, contract) only, which was too aggressive
(it kept one row per cycle and removed other valid strikes). If you ever need
to dedupe again, use (date, contract, strike, side) and keep min(id) per that
group so only true same-strike duplicates are removed.

Run from project root: python -m backend.util.dedupe_simulated_trades
"""
import os
import sys

# From backend/util/ we need to go up to project root (two levels)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.chdir(_project_root)

from backend.core.config.database import get_postgresql_connection


def main():
    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to database")
        sys.exit(1)
    try:
        with conn.cursor() as cur:
            # Count duplicates (rows that are not the minimum id for their date+contract)
            cur.execute("""
                SELECT COUNT(*) FROM users.trades_simulated_0001 t1
                WHERE EXISTS (
                    SELECT 1 FROM users.trades_simulated_0001 t2
                    WHERE t2.date IS NOT DISTINCT FROM t1.date
                      AND t2.contract IS NOT DISTINCT FROM t1.contract
                      AND t2.id < t1.id
                )
            """)
            to_delete = cur.fetchone()[0]
            if to_delete == 0:
                print("No duplicate rows (by date, contract) found.")
                return
            # Delete all but the earliest (min id) per (date, contract)
            cur.execute("""
                DELETE FROM users.trades_simulated_0001 t1
                USING users.trades_simulated_0001 t2
                WHERE t2.date IS NOT DISTINCT FROM t1.date
                  AND t2.contract IS NOT DISTINCT FROM t1.contract
                  AND t2.id < t1.id
            """)
            deleted = cur.rowcount
        conn.commit()
        print(f"Deleted {deleted} duplicate row(s). Kept earliest trade per (date, contract).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
