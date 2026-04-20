#!/usr/bin/env python3
"""
Report trades with monitor_confirmed = FALSE so we can track whether the problem
persists or expands to other monitors/strategies.

Run from project root. Use --days to set the lookback window; use --append-log
to append a one-line summary to the log file for trend tracking.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no

LOG_FILE = os.path.join(SCRIPT_DIR, "monitor_confirmed_failures_log.txt")


def main():
    ap = argparse.ArgumentParser(description="Report monitor_confirmed=FALSE trades")
    add_user_no_argument(ap)
    ap.add_argument("--days", type=int, default=7, help="Lookback days (default 7)")
    ap.add_argument("--append-log", action="store_true", help="Append one-line summary to log file")
    args = ap.parse_args()
    user_no = resolve_user_no(args)
    trades_t = legacy_users_trades(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("No database connection.", file=sys.stderr)
        sys.exit(1)

    cutoff = (datetime.now(ZoneInfo("America/New_York")) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, monitor, trade_strategy, high_price, low_price, ticker, closed_at, date
            FROM {trades_t}
            WHERE status = %s AND monitor_confirmed = %s AND date >= %s
            ORDER BY date, closed_at, id
            """,
            ("closed", False, cutoff),
        )
        rows = cur.fetchall()
    conn.close()

    # Classify each row
    null_null = []   # (monitor, strategy) -> count
    high_eq_low = [] # (monitor, strategy) -> count
    by_key = {}      # (monitor, strategy) -> list of (id, high, low)

    for r in rows:
        id_, monitor, strategy, high, low, ticker, closed_at, date = r
        key = (monitor or "?", strategy or "?")
        if key not in by_key:
            by_key[key] = []
        by_key[key].append((id_, high, low))
        if high is None and low is None:
            null_null.append(key)
        else:
            high_eq_low.append(key)

    # Count by (monitor, strategy)
    from collections import Counter
    null_counts = Counter(null_null)
    high_eq_low_counts = Counter(high_eq_low)

    # Report
    print(f"monitor_confirmed = FALSE (since {cutoff}, last {args.days} days)")
    print(f"Total: {len(rows)} trades")
    print()

    if not rows:
        print("No failures in this window.")
        if args.append_log:
            with open(LOG_FILE, "a") as f:
                f.write(f"{datetime.now(ZoneInfo('America/New_York')).isoformat()} | days={args.days} | total=0\n")
        return

    print("By monitor and strategy:")
    print("-" * 60)
    for key in sorted(by_key.keys()):
        mon, strat = key
        entries = by_key[key]
        n_null = sum(1 for (_, h, l) in entries if h is None and l is None)
        n_high_low = len(entries) - n_null
        parts = []
        if n_null:
            parts.append(f"NULL={n_null}")
        if n_high_low:
            parts.append(f"high==low={n_high_low}")
        print(f"  {mon}  {strat}: {len(entries)}  ({', '.join(parts)})")
    print("-" * 60)
    print("Failure modes: NULL/NULL = trade not in ATS active_trades at close; high==low = ATS had trade but never updated (e.g. ticker gone after event rotation).")
    print()

    if args.append_log:
        parts = [f"{k[0]}/{k[1]}={len(by_key[k])}" for k in sorted(by_key.keys())]
        line = f"{datetime.now(ZoneInfo('America/New_York')).isoformat()} | days={args.days} | total={len(rows)} | " + " | ".join(parts) + "\n"
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line)
            print(f"Appended to {LOG_FILE}")
        except Exception as e:
            print(f"Could not append to log: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
