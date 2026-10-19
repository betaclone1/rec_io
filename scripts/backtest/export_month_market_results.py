#!/usr/bin/env python3
"""
Export per-month market_result CSVs next to day public-trade files.

Reads `.cache_market_result_by_ticker.json` (optionally refresh via
`fetch_kxbtc15m_market_results_bulk.py` first). For each calendar day in the
month that has a day CSV (or --all-slots), emit one row per synthetic 15m
ticker with authoritative yes/no when present; leave market_result blank when
unknown (no invented settlements).

Output:
  backend/data/historical_data/kalshi_public_trades/
    {series}_market_results_{YYYY-MM}_et.csv

Example:
  PYTHONPATH=. .venv/bin/python3 scripts/backtest/export_month_market_results.py \
    --series KXBTC15M --year 2026 --month 9
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.backtest.helpers.kalshi_ticker_construct import (
    kalshi_15m_market_tickers_for_eastern_date,
)

TRADES_DIR = _ROOT / "backend" / "data" / "historical_data" / "kalshi_public_trades"
CACHE_JSON = TRADES_DIR / ".cache_market_result_by_ticker.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True)
    ap.add_argument(
        "--all-slots",
        action="store_true",
        help="Include every synthetic ticker for the month even if day CSV missing.",
    )
    args = ap.parse_args()

    series = str(args.series).strip().upper()
    cache: dict = {}
    if CACHE_JSON.is_file():
        raw = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cache = raw

    last = calendar.monthrange(args.year, args.month)[1]
    days = [date(args.year, args.month, d) for d in range(1, last + 1)]
    tag = f"{args.year}-{args.month:02d}"
    out = TRADES_DIR / f"{series}_market_results_{tag}_et.csv"

    rows: list[dict[str, str]] = []
    have = missing = skipped_no_day = 0
    for d in days:
        day_csv = TRADES_DIR / f"{series}_public_trades_{d.isoformat()}_et.csv"
        if not day_csv.is_file() and not args.all_slots:
            skipped_no_day += 1
            continue
        for t in kalshi_15m_market_tickers_for_eastern_date(series, d):
            ent = cache.get(t) or {}
            mr = ent.get("mr") if isinstance(ent, dict) else None
            if mr not in ("yes", "no"):
                mr = ""
                missing += 1
            else:
                have += 1
            rows.append(
                {
                    "date_et": d.isoformat(),
                    "ticker": t,
                    "market_result": mr,
                    "source": str((ent or {}).get("source") or "") if mr else "",
                }
            )

    TRADES_DIR.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["date_et", "ticker", "market_result", "source"]
        )
        w.writeheader()
        w.writerows(rows)

    print(
        f"wrote {out} rows={len(rows)} with_result={have} "
        f"blank={missing} days_without_csv_skipped={skipped_no_day}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
