#!/usr/bin/env python3
"""
Read-only diagnostic: Inspect today's BTC 2:00pm cycle in users.trades_simulated_0001.
- List triggers on the table (if any) that might set updated_at.
- List all rows for that cycle with id, date, contract, time, strike, side, prob, created_at, updated_at.
- Show whether updated_at > created_at (row was updated after insert; only possible if trigger exists or app sets updated_at).
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
os.chdir(project_root)

from backend.core.config.database import get_postgresql_connection

def main():
    today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to database")
        sys.exit(1)
    try:
        with conn.cursor() as cur:
            # 1) Triggers on trades_simulated_0001
            cur.execute("""
                SELECT tgname, pg_get_triggerdef(t.oid, true)
                FROM pg_trigger t
                JOIN pg_class c ON t.tgrelid = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = 'users' AND c.relname = 'trades_simulated_0001'
                AND NOT t.tgisinternal
            """)
            triggers = cur.fetchall()
            print("--- Triggers on users.trades_simulated_0001 ---")
            if not triggers:
                print("(none – updated_at is only set on INSERT default; no trigger updates it)")
            else:
                for name, defn in triggers:
                    print(f"  {name}: {defn}")

            # 2) Columns created_at / updated_at exist?
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'users' AND table_name = 'trades_simulated_0001'
                AND column_name IN ('created_at', 'updated_at')
                ORDER BY 1
            """)
            cols = cur.fetchall()
            print("\n--- created_at / updated_at columns ---")
            for c in cols:
                print(f"  {c[0]}: {c[1]}")

            # 3) Today's BTC 2:00pm cycle – all rows (contract = 'BTC 2:00pm', date = today)
            cur.execute("""
                SELECT id, date, contract, time, strike, side, prob,
                       created_at, updated_at,
                       (updated_at IS DISTINCT FROM created_at) AS was_updated
                FROM users.trades_simulated_0001
                WHERE symbol = %s AND contract = %s AND date = %s
                ORDER BY id
            """, ("BTC", "BTC 2:00pm", today))
            rows = cur.fetchall()
            print(f"\n--- Today ({today}) BTC 2:00pm cycle: {len(rows)} row(s) ---")
            if not rows:
                print("(no rows found)")
            else:
                for r in rows:
                    (id_, date_, contract, time_, strike, side, prob,
                     created_at, updated_at, was_updated) = r
                    print(f"  id={id_} date={date_} contract={contract!r} time={time_!r} "
                          f"strike={strike} side={side} prob={prob}")
                    print(f"    created_at={created_at} updated_at={updated_at} was_updated={was_updated}")
                # Duplicate (strike, side) in this cycle?
                cur.execute("""
                    SELECT strike, side, COUNT(*) AS n, array_agg(id ORDER BY id) AS ids
                    FROM users.trades_simulated_0001
                    WHERE symbol = %s AND contract = %s AND date = %s
                    GROUP BY date, contract, strike, side
                    HAVING COUNT(*) > 1
                """, ("BTC", "BTC 2:00pm", today))
                dups = cur.fetchall()
                if dups:
                    print("\n  DUPLICATE (strike, side) in this cycle:", dups)
                else:
                    print("\n  No duplicate (strike, side) in this cycle.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
