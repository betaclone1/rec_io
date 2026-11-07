#!/usr/bin/env python3
"""
Catch up day public-trade CSVs + market_result cache/exports for tracked 15m series.

Skips days that already have a non-empty CSV. Refreshes shared
``.cache_market_result_by_ticker.json`` per series, then rewrites month
``{series}_market_results_{YYYY-MM}_et.csv`` for months touched by the catch-up
window (and always the current Eastern month).

Example:
  nohup .venv/bin/python -u scripts/backtest/catchup_public_trades_and_market_results.py \\
    --end-today >> logs/catchup.log 2>&1 &
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

OUT_DIR = _ROOT / "backend" / "data" / "historical_data" / "kalshi_public_trades"
EST = ZoneInfo("America/New_York")

DEFAULT_SERIES = (
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXGOLD15M",
    "KXSILVER15M",
    "KXWTI15M",
)


def _et_today() -> date:
    return datetime.now(EST).date()


def _missing_days(series: str, start: date, end: date) -> list[date]:
    miss: list[date] = []
    d = start
    while d <= end:
        p = OUT_DIR / f"{series}_public_trades_{d.isoformat()}_et.csv"
        if not p.is_file() or p.stat().st_size <= 0:
            miss.append(d)
        d += timedelta(days=1)
    return miss


def _run(argv: list[str], *, label: str) -> int:
    print(f"RUN {label}: {' '.join(argv)}", flush=True)
    t0 = time.time()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    proc = subprocess.run(argv, cwd=str(_ROOT), env=env)
    print(
        f"DONE {label} rc={proc.returncode} elapsed={time.time() - t0:.1f}s",
        flush=True,
    )
    return int(proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--series",
        nargs="+",
        default=list(DEFAULT_SERIES),
        help="Kalshi 15m series tickers",
    )
    ap.add_argument(
        "--start",
        help="Eastern YYYY-MM-DD inclusive (default: 21d before end)",
    )
    ap.add_argument(
        "--end",
        help="Eastern YYYY-MM-DD inclusive (default: yesterday ET, or today with --end-today)",
    )
    ap.add_argument(
        "--end-today",
        action="store_true",
        help="Include today's Eastern date (partial day OK)",
    )
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--skip-trades",
        action="store_true",
        help="Only refresh market results",
    )
    ap.add_argument(
        "--skip-results",
        action="store_true",
        help="Only pull public trade day CSVs",
    )
    args = ap.parse_args()

    today = _et_today()
    end = date.fromisoformat(args.end) if args.end else (
        today if args.end_today else today - timedelta(days=1)
    )
    start = (
        date.fromisoformat(args.start)
        if args.start
        else end - timedelta(days=21)
    )
    if end < start:
        raise SystemExit(f"end {end} < start {start}")

    py = str(_ROOT / ".venv" / "bin" / "python")
    if not Path(py).is_file():
        py = sys.executable

    print(
        f"CATCHUP_START series={args.series} window={start}..{end} "
        f"et_today={today} workers={args.workers}",
        flush=True,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    months: set[tuple[int, int]] = {(end.year, end.month), (start.year, start.month)}

    if not args.skip_trades:
        for series in args.series:
            miss = _missing_days(series, start, end)
            print(f"TRADES {series} missing_days={len(miss)} {miss}", flush=True)
            for d in miss:
                months.add((d.year, d.month))
                rc = _run(
                    [
                        py,
                        "scripts/backtest/pull_kxbtc15m_public_trades_day_csv.py",
                        "--date",
                        d.isoformat(),
                        "--series",
                        series,
                        "--workers",
                        str(args.workers),
                    ],
                    label=f"trades:{series}:{d.isoformat()}",
                )
                if rc != 0:
                    failed.append(f"trades:{series}:{d.isoformat()}:rc={rc}")

    if not args.skip_results:
        for series in args.series:
            rc = _run(
                [
                    py,
                    "scripts/backtest/fetch_kxbtc15m_market_results_bulk.py",
                    "--series",
                    series,
                ],
                label=f"results_bulk:{series}",
            )
            if rc != 0:
                failed.append(f"results_bulk:{series}:rc={rc}")

        for series in args.series:
            for y, m in sorted(months):
                rc = _run(
                    [
                        py,
                        "scripts/backtest/export_month_market_results.py",
                        "--series",
                        series,
                        "--year",
                        str(y),
                        "--month",
                        str(m),
                    ],
                    label=f"results_month:{series}:{y}-{m:02d}",
                )
                if rc != 0:
                    failed.append(f"results_month:{series}:{y}-{m:02d}:rc={rc}")

    print(f"CATCHUP_FAILED={failed}", flush=True)
    print("CATCHUP_DONE", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
