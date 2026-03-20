#!/usr/bin/env python3
"""Export users.account_history_0001 to CSV on stdout. Run from repo root with PYTHONPATH."""
import csv
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from backend.core.config.database import get_postgresql_connection

def main():
    conn = get_postgresql_connection()
    if not conn:
        sys.exit(1)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, entry_type, amount, fee, created_at, updated_at, status, returned_amount, "
        "deposit_type, immediate_amount, immediate_status, synced_at, kalshi_id, vendor, rail "
        "FROM users.account_history_0001 ORDER BY created_at DESC"
    )
    rows = cur.fetchall()
    colnames = [d[0] for d in cur.description]
    w = csv.writer(sys.stdout)
    w.writerow(colnames)
    for r in rows:
        w.writerow([str(x) if x is not None else "" for x in r])
    conn.close()

if __name__ == "__main__":
    main()
