#!/usr/bin/env python3
"""
Pull Kalshi 1m candlesticks for a market's ``open_time``..``close_time`` into a **scratch** table:

  historical_data.kalshi_candles_1m_<ticker_slug>_YYYYMMDD

``YYYYMMDD`` is the **UTC calendar date** you choose (default: today), so re-runs the same day
upsert into the same table; older suffixes can be dropped with ``--cleanup-only``.

Uses the same column layout as testing candlestick tables (``timestamp`` first, US Eastern naive).

**Hourly vs 15m (and other durations):** The API window is always the market’s ``open_time``..``close_time`` with ``period_interval=1``. You get one row per minute in that window (e.g. **60** bars for a one-hour contract, **15** for a 15-minute contract). ``--series`` defaults to the ticker prefix before the first ``-`` (e.g. ``KXBTCD`` vs ``KXBTC15M``).

Connection: ``scripts/backtest/helpers/db.py`` (``REC_IO_BACKTEST_DB=local`` or ``prod``).

Examples::

  REC_IO_BACKTEST_DB=local .venv/bin/python3 scripts/backtest/helpers/kalshi_market_candles_scratch.py \\
    --ticker KXBTCD-26JAN1320-T95499.99

  REC_IO_BACKTEST_DB=local .venv/bin/python3 scripts/backtest/helpers/kalshi_market_candles_scratch.py \\
    --ticker KXBTC15M-26MAR191745-45

  .venv/bin/python3 scripts/backtest/helpers/kalshi_market_candles_scratch.py --cleanup-only --retention-days 1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

HELPERS_DIR = os.path.dirname(os.path.abspath(__file__))
if HELPERS_DIR not in sys.path:
    sys.path.insert(0, HELPERS_DIR)

from db import get_connection  # noqa: E402
from kalshi_candles_1m import (  # noqa: E402
    cleanup_stale_scratch_tables,
    ensure_historical_schema,
    ensure_scratch_table,
    run_fill,
    scratch_table_name,
    scratch_table_qualified,
)


def _parse_as_of(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    p = argparse.ArgumentParser(description="Kalshi 1m candles → historical_data scratch table.")
    p.add_argument("--ticker", help="Full Kalshi market ticker")
    p.add_argument(
        "--series",
        default=None,
        help="Series ticker (default: segment before first '-' in ticker)",
    )
    p.add_argument(
        "--as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="UTC date suffix for table name (default: UTC today)",
    )
    p.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Only drop old scratch tables; no fetch",
    )
    p.add_argument(
        "--retention-days",
        type=int,
        default=1,
        help="Drop tables whose _YYYYMMDD suffix is before UTC today minus this many days (default: 1)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="With --cleanup-only, print DROP statements only",
    )
    p.add_argument(
        "--cleanup-after",
        action="store_true",
        help="After a successful pull, run the same cleanup as --cleanup-only",
    )
    args = p.parse_args()

    if args.cleanup_only:
        if args.ticker:
            p.error("--cleanup-only does not use --ticker")
        conn = get_connection()
        try:
            dropped = cleanup_stale_scratch_tables(
                conn, retention_days=args.retention_days, dry_run=args.dry_run
            )
            if not args.dry_run:
                conn.commit()
        except Exception as e:
            conn.rollback()
            print(e, file=sys.stderr)
            return 1
        finally:
            conn.close()
        if not dropped:
            print("No stale scratch tables matched cleanup rules.")
        else:
            for line in dropped:
                print(line)
        return 0

    if not args.ticker:
        p.error("--ticker is required unless --cleanup-only")

    as_of = _parse_as_of(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    rel = scratch_table_name(args.ticker, as_of)
    target = scratch_table_qualified(rel)

    conn = get_connection()
    try:
        ensure_historical_schema(conn)
        ensure_scratch_table(conn, rel, args.ticker)
        open_u, close_u, n = run_fill(
            conn,
            args.ticker,
            args.series,
            target_table=target,
        )
        conn.commit()
        print(f"Upserted {n} rows into {target}")
        print(f"Window unix: {open_u} .. {close_u}")

        if args.cleanup_after:
            dropped = cleanup_stale_scratch_tables(
                conn, retention_days=args.retention_days, dry_run=False
            )
            conn.commit()
            if dropped:
                print("Cleanup dropped:", ", ".join(dropped))
    except Exception as e:
        conn.rollback()
        print(e, file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
