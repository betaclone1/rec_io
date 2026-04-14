#!/usr/bin/env python3
"""
One-off: fetch /deposits and /withdrawals from Kalshi v1, then backfill kalshi_id/vendor/rail
on existing users.account_history_0001 rows that have them NULL. Also refreshes transfer from/to.

Run from project root: PYTHONPATH=. python3 scripts/backfill_account_history_vendor_rail.py

Uses same credentials and DB as kalshi_account_sync_ws (account_mode, get_kalshi_credentials_dir).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from backend.core.config.database import get_system_postgresql_connection

    conn = get_system_postgresql_connection()
    if not conn:
        print("Failed to connect to database.")
        return 1

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kalshi_user_id FROM system.master_users
            WHERE LPAD(TRIM(user_no::text), 4, '0') = '0001'
            LIMIT 1
            """
        )
        row = cur.fetchone()
    kalshi_user_id = (row[0] or "").strip() if row and row[0] else None
    if not kalshi_user_id:
        print("No kalshi_user_id in system.master_users for user_no 0001.")
        return 1

    from backend.kalshi_account_sync_ws import (
        fetch_v1_deposits_page,
        fetch_v1_withdrawals_page,
        _backfill_account_history_vendor_rail,
    )

    page_size = 200
    all_deposits = []
    page_number = 1
    while True:
        deposits, err = fetch_v1_deposits_page(kalshi_user_id, page_number=page_number, page_size=page_size)
        if err:
            print(f"Deposits fetch failed: {err}")
            return 1
        all_deposits.extend(deposits)
        if len(deposits) < page_size:
            break
        page_number += 1
    all_withdrawals = []
    page_number = 1
    while True:
        withdrawals, err = fetch_v1_withdrawals_page(kalshi_user_id, page_number=page_number, page_size=page_size)
        if err:
            print(f"Withdrawals fetch failed: {err}")
            return 1
        all_withdrawals.extend(withdrawals)
        if len(withdrawals) < page_size:
            break
        page_number += 1

    print(f"Fetched {len(all_deposits)} deposits, {len(all_withdrawals)} withdrawals.")
    _backfill_account_history_vendor_rail(conn, all_deposits, all_withdrawals)
    conn.close()
    print("Backfill and transfer refresh done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
