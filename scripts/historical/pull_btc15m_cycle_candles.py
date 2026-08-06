#!/usr/bin/env python3
"""Pull KXBTC15M cycle candles into historical_data.btc15m_cycle_candles.

Uses the same Kalshi market + /live_data/events timeseries path as trade-history
detail charts. Open = floor_strike; high/low/close from timeseries.

Examples:
  # First 10 cycles of an Eastern calendar day
  PYTHONPATH=$(pwd) venv/bin/python scripts/historical/pull_btc15m_cycle_candles.py \\
    --date 2026-08-02 --limit 10

  # All cycles from Jan 1 through today (Eastern)
  PYTHONPATH=$(pwd) venv/bin/python scripts/historical/pull_btc15m_cycle_candles.py \\
    --start-date 2026-01-01 --end-date 2026-08-02
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.btc15m_cycle_candles import (  # noqa: E402
    fetch_cycle_candle,
    upsert_cycle_candle,
)
from backend.core.config.database import get_system_postgresql_connection  # noqa: E402
from backend.core.trade_history_detail import KalshiDetailError  # noqa: E402
from scripts.backtest.helpers.kalshi_ticker_construct import (  # noqa: E402
    kalshi_15m_market_tickers_for_eastern_date,
    kalshi_15m_market_tickers_for_eastern_date_range,
    parse_eastern_trading_day_arg,
)

_EASTERN = ZoneInfo("America/New_York")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--date",
        default=None,
        help="Single Eastern calendar day YYYY-MM-DD",
    )
    p.add_argument(
        "--start-date",
        default=None,
        help="Eastern range start YYYY-MM-DD (inclusive); use with --end-date",
    )
    p.add_argument(
        "--end-date",
        default=None,
        help="Eastern range end YYYY-MM-DD (inclusive); default today ET if omitted with --start-date",
    )
    p.add_argument(
        "--series",
        default="KXBTC15M",
        help="Kalshi 15m series ticker (default KXBTC15M)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If >0, only the first N tickers of the selection (chronological)",
    )
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N tickers before applying --limit",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Seconds between Kalshi fetches (rate limit courtesy)",
    )
    p.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print a progress line every N tickers (0 = every ticker detail)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print rows; do not write to Postgres",
    )
    p.add_argument(
        "--require-prices",
        action="store_true",
        help="Skip upsert when timeseries is empty (still print)",
    )
    return p.parse_args()


def _today_eastern() -> date:
    return datetime.now(_EASTERN).date()


def _resolve_tickers(args: argparse.Namespace) -> list[str]:
    if args.date and (args.start_date or args.end_date):
        raise SystemExit("Use either --date or --start-date/--end-date, not both")
    if args.date:
        day = parse_eastern_trading_day_arg(args.date)
        tickers = kalshi_15m_market_tickers_for_eastern_date(args.series, day)
        label = f"day={day.isoformat()}"
    elif args.start_date:
        start = parse_eastern_trading_day_arg(args.start_date)
        end = (
            parse_eastern_trading_day_arg(args.end_date)
            if args.end_date
            else _today_eastern()
        )
        if end < start:
            raise SystemExit(f"end-date {end} must be >= start-date {start}")
        tickers = kalshi_15m_market_tickers_for_eastern_date_range(
            args.series, start, end
        )
        label = f"start={start.isoformat()} end={end.isoformat()}"
    else:
        raise SystemExit("Provide --date or --start-date")

    if args.offset:
        tickers = tickers[args.offset :]
    if args.limit and args.limit > 0:
        tickers = tickers[: args.limit]
    print(f"{label} series={args.series} count={len(tickers)}")
    return tickers


def main() -> int:
    args = _parse_args()
    tickers = _resolve_tickers(args)
    if not tickers:
        print("No tickers selected", file=sys.stderr)
        return 1

    if len(tickers) <= 20:
        for t in tickers:
            print(f"  {t}")
    else:
        print(f"  first={tickers[0]}")
        print(f"  last={tickers[-1]}")

    conn = None
    if not args.dry_run:
        conn = get_system_postgresql_connection()
        if not conn:
            print("No Postgres connection", file=sys.stderr)
            return 1

    ok = 0
    failed = 0
    skipped = 0
    started = time.time()
    try:
        for i, ticker in enumerate(tickers):
            if i and args.sleep > 0:
                time.sleep(args.sleep)
            try:
                row, meta = fetch_cycle_candle(ticker)
                points = int(meta.get("price_points") or 0)
                detail = (
                    args.progress_every <= 0
                    or (i + 1) % args.progress_every == 0
                    or i == 0
                    or i + 1 == len(tickers)
                )
                if detail:
                    elapsed = time.time() - started
                    rate = (i + 1) / elapsed if elapsed > 0 else 0.0
                    eta = (len(tickers) - i - 1) / rate if rate > 0 else 0.0
                    print(
                        f"[{i + 1}/{len(tickers)}] OK {ticker} "
                        f"floor={row.get('floor_strike')} close={row.get('close')} "
                        f"result={row.get('market_result')} points={points} "
                        f"ok={ok} fail={failed} "
                        f"rate={rate:.2f}/s eta={eta / 60:.1f}m"
                    )
                if args.require_prices and points <= 0:
                    skipped += 1
                    print(f"SKIP {ticker}: no timeseries prices", file=sys.stderr)
                    continue
                if args.dry_run:
                    ok += 1
                    continue
                assert conn is not None
                with conn.cursor() as cur:
                    upsert_cycle_candle(cur, row)
                conn.commit()
                ok += 1
            except (KalshiDetailError, ValueError) as exc:
                failed += 1
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                print(f"FAIL {ticker}: {exc}", file=sys.stderr)
                continue
            except Exception as exc:
                # Keep walking the range when one cycle/row is corrupt or overflows.
                failed += 1
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                print(
                    f"FAIL {ticker}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                continue
    finally:
        if conn is not None:
            conn.close()

    print(
        f"done ok={ok} failed={failed} skipped={skipped} "
        f"dry_run={args.dry_run} elapsed_s={time.time() - started:.1f}"
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONPATH", str(ROOT))
    raise SystemExit(main())
