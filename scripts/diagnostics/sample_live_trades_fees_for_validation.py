#!/usr/bin/env python3
"""
Sample live (non-paper) closed trades from production DB where fees were recorded,
and compare actual fees to Kalshi taker formula: round_up(0.07 * C * P * (1-P)) per leg.

Use this to validate the fee methodology before implementing paper-trade fee estimates.
Run from project root with DB env vars pointing at production (or local if you have live data):

  PYTHONPATH=$(pwd) python3 scripts/diagnostics/sample_live_trades_fees_for_validation.py [--limit N] [--seed S]

Read-only: SELECT only; no writes.
"""

import argparse
import math
import os
import random
import sys

# Use project DB config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no


def round_up_cents(dollars: float) -> float:
    """Round up to the next cent (Kalshi convention)."""
    if dollars <= 0:
        return 0.0
    return math.ceil(dollars * 100) / 100


def estimate_kalshi_taker_fee(position: int, price: float) -> float:
    """Estimate taker fee for one leg: 0.07 * C * P * (1-P), rounded up to nearest cent."""
    if position is None or position <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = 0.07 * position * price * (1.0 - price)
    return round_up_cents(raw)


def main():
    parser = argparse.ArgumentParser(description="Sample live trades with fees for fee-formula validation")
    add_user_no_argument(parser)
    parser.add_argument("--limit", type=int, default=30, help="Max number of trades to sample (default 30)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sample")
    parser.add_argument("--no-random", action="store_true", help="Take first N by id instead of random sample")
    args = parser.parse_args()
    user_no = resolve_user_no(args)
    trades_t = legacy_users_trades(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to connect to database. Set DB_HOST, DB_NAME, DB_USER, DB_PASSWORD (or REC_DB_*) for production.")
        sys.exit(1)

    # Live trades only (paper_trade = false), closed/expired, with non-null positive fees.
    # Position >= 100 only: small positions (e.g. single contracts) break down with the fee formula.
    query = f"""
    SELECT id, buy_price, position, sell_price, fees, pnl, close_method, status, ticker, date, created_at
    FROM {trades_t}
    WHERE (paper_trade IS NULL OR paper_trade = false)
      AND status IN ('closed', 'expired')
      AND fees IS NOT NULL AND fees > 0
      AND buy_price IS NOT NULL AND position IS NOT NULL AND position >= 100
      AND sell_price IS NOT NULL
    ORDER BY id
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            colnames = [d[0] for d in cur.description]
    finally:
        conn.close()

    if not rows:
        print("No live closed trades with fees recorded. Try another DB or relax filters.")
        return

    trades = [dict(zip(colnames, row)) for row in rows]

    # Random sample (or first N)
    if args.no_random:
        sample = trades[: args.limit]
    else:
        if args.seed is not None:
            random.seed(args.seed)
        sample = random.sample(trades, min(args.limit, len(trades)))

    print(f"Sampled {len(sample)} of {len(trades)} live closed trades with fees > 0\n")
    print("Kalshi taker formula per leg: fee = round_up(0.07 * position * price * (1 - price))")
    print("Open leg: price = buy_price. Close leg: price = 1 - sell_price (we buy to close at that price).")
    print("-" * 100)

    for t in sample:
        tid = t["id"]
        buy_price = float(t["buy_price"]) if t["buy_price"] is not None else None
        position = int(t["position"]) if t["position"] is not None else None
        sell_price = float(t["sell_price"]) if t["sell_price"] is not None else None
        actual_fees = float(t["fees"]) if t["fees"] is not None else None
        close_method = t["close_method"] or ""

        # Close: we record sell_price (what we got); the closing order is a buy at (1 - sell_price). Fee is on that execution price.
        price_to_close = (1.0 - sell_price) if sell_price is not None else None
        open_fee_est = estimate_kalshi_taker_fee(position, buy_price)
        close_fee_est = estimate_kalshi_taker_fee(position, price_to_close) if price_to_close and 0 < price_to_close < 1 else 0.0
        total_est = open_fee_est + close_fee_est

        diff = (actual_fees - total_est) if actual_fees is not None else None
        match = "OK" if diff is not None and abs(diff) < 0.02 else ("LOW" if diff and diff > 0.02 else "HIGH")
        diff_str = f"{diff:.4f}" if diff is not None else "N/A"

        print(f"id={tid} ticker={t['ticker']} date={t['date']} close_method={close_method}")
        print(f"  position={position} buy_price={buy_price} sell_price={sell_price}")
        print(f"  actual_fees={actual_fees:.4f}  open_est={open_fee_est:.4f} close_est={close_fee_est:.4f} total_est={total_est:.4f}  diff={diff_str}  [{match}]")
        print()

    # Summary stats
    diffs = []
    for t in sample:
        buy_price = float(t["buy_price"]) if t["buy_price"] else None
        position = int(t["position"]) if t["position"] else None
        sell_price = float(t["sell_price"]) if t["sell_price"] else None
        actual_fees = float(t["fees"]) if t["fees"] else None
        if None in (buy_price, position, sell_price, actual_fees):
            continue
        price_to_close = (1.0 - sell_price) if sell_price is not None and 0 < sell_price < 1 else None
        open_est = estimate_kalshi_taker_fee(position, buy_price)
        close_est = estimate_kalshi_taker_fee(position, price_to_close) if price_to_close else 0.0
        total_est = open_est + close_est
        diffs.append(actual_fees - total_est)

    if diffs:
        avg_diff = sum(diffs) / len(diffs)
        within_2c = sum(1 for d in diffs if abs(d) < 0.02)
        print("-" * 100)
        print(f"Summary: n={len(diffs)}  avg(actual - estimated) = {avg_diff:.4f}  within 2¢: {within_2c}/{len(diffs)}")


if __name__ == "__main__":
    main()
