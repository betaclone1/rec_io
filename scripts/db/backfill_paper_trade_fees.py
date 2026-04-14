#!/usr/bin/env python3
"""
Backfill users.trades_0001.fees for rows where paper_trade = TRUE only.
Uses taker formula: open_fee = round_up(0.07 * position * buy_price * (1 - buy_price));
for closed-before-expiration adds close_fee = round_up(0.07 * position * (1 - sell_price) * sell_price).
Updates ONLY the fees column; does not touch any row where paper_trade is not TRUE.

Run against production with: DB_HOST=$REC_PROD_SSH_HOST PYTHONPATH=$(pwd) python3 scripts/db/backfill_paper_trade_fees.py --user-no 0001
(Canonical prod IPv4 and env: docs/PRODUCTION_HOST.md — currently 165.22.13.146.)
Dry run (no writes): add --dry-run
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no
from psycopg2 import extras


def estimate_kalshi_taker_fee(position: int, price: float) -> float:
    if position is None or position <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = 0.07 * position * float(price) * (1.0 - float(price))
    return math.ceil(raw * 100) / 100


def main():
    parser = argparse.ArgumentParser(description="Backfill paper trade fees (fees column only)")
    add_user_no_argument(parser)
    parser.add_argument("--dry-run", action="store_true", help="Do not UPDATE; only report what would be set")
    args = parser.parse_args()
    user_no = resolve_user_no(args)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to connect to database.")
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, buy_price, position, sell_price, close_method
            FROM users.trades_0001
            WHERE paper_trade = TRUE
        """)
        rows = cur.fetchall()

    if not rows:
        print("No paper trades found.")
        conn.close()
        return

    updates = []
    for row in rows:
        id_, buy_price, position, sell_price, close_method = row
        try:
            pos = int(position) if position is not None else None
            bp = float(buy_price) if buy_price is not None else None
            sp = float(sell_price) if sell_price is not None else None
        except (TypeError, ValueError):
            updates.append((id_, 0.0))
            continue
        open_fee = estimate_kalshi_taker_fee(pos, bp) if (pos and bp is not None) else 0.0
        if sp is not None and close_method and str(close_method).lower() != "expired":
            price_to_close = 1.0 - sp
            close_fee = estimate_kalshi_taker_fee(pos, price_to_close) if 0 < price_to_close < 1 else 0.0
            total = open_fee + close_fee
        else:
            total = open_fee
        updates.append((id_, total))

    if args.dry_run:
        print(f"DRY RUN: would set fees for {len(updates)} paper trade(s). Sample: id={updates[0][0]} fees={updates[0][1]}")
        conn.close()
        return

    # Single UPDATE from VALUES to avoid 3k+ round-trips
    with conn.cursor() as cur:
        extras.execute_values(
            cur,
            """
            UPDATE users.trades_0001 AS t
            SET fees = v.fees
            FROM (VALUES %s) AS v(id, fees)
            WHERE t.id = v.id::bigint AND t.paper_trade = TRUE
            """,
            updates,
            template="(%s::bigint, %s::numeric)",
            page_size=500,
        )
    conn.commit()
    conn.close()
    print(f"Updated fees for {len(updates)} paper trade(s).")


if __name__ == "__main__":
    main()
